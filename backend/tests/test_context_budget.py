import pytest
import pytest_asyncio
from types import SimpleNamespace

from app.config import get_settings
from app.db import close_db, init_db
from app.llm.client import MockLLMClient, set_llm_client
from app.models import Chapter, Novel, Outline, OutlineItem
from app.services.context_builder import (
    BUDGET,
    BuiltContext,
    format_recent_chapters,
    build_context,
)
from app.utils.chinese_text import count_tokens
import app.db as db_mod
import app.llm.client as llm_mod


def test_budget_constants():
    assert BUDGET["recent"] == 8000
    assert BUDGET["bible"] == 2500
    # bible 高优先级；recent 超预算时改用章尾
    assert BUDGET["recent"] + BUDGET["bible"] > BUDGET["rag"]


def test_trim_priority_logic():
    """模拟裁剪优先级：卷摘要 → RAG → 章摘要。"""
    trimmed: list[str] = []
    include_vol = True
    rag_n = 8
    chap_n = 5

    def used_tokens(vol: bool, rag: int, chap: int, style_len: int) -> int:
        return (500 if vol else 0) + rag * 200 + chap * 300 + style_len

    style_len = 800
    # 假设预算很紧
    flexible = 1500
    while used_tokens(include_vol, rag_n, chap_n, style_len) > flexible:
        if include_vol:
            include_vol = False
            trimmed.append("volume_summaries")
            continue
        if rag_n > 3:
            rag_n -= 1
            trimmed.append("rag")
            continue
        if chap_n > 2:
            chap_n -= 1
            trimmed.append("chapter_summaries")
            continue
        style_len = max(200, style_len // 2)
        trimmed.append("style")
        break

    assert trimmed[0] == "volume_summaries"
    assert "rag" in trimmed
    assert chap_n >= 2


def test_built_context_dataclass():
    ctx = BuiltContext(recent_chapters="最近两章", story_bible="人物")
    assert count_tokens(ctx.recent_chapters) > 0


def test_short_recent_chapters_keep_full_text():
    chs = [
        SimpleNamespace(title="第一章", content="叶凡醒来。"),
        SimpleNamespace(title="第二章", content="苏婉现身。"),
    ]
    text = format_recent_chapters(chs, budget_tokens=8000)
    assert "叶凡醒来。" in text
    assert "苏婉现身。" in text
    assert "章尾" not in text


def test_long_recent_chapters_use_endings():
    prev = SimpleNamespace(
        title="第三十九章",
        content="【章首A】" + "甲" * 12000 + "【章尾A】",
    )
    last = SimpleNamespace(
        title="第四十章",
        content="【章首B】" + "乙" * 12000 + "【章尾B】",
    )
    text = format_recent_chapters([prev, last], budget_tokens=8000)
    assert "【章尾A】" in text
    assert "【章尾B】" in text
    assert "【章首A】" not in text
    assert "【章首B】" not in text
    assert "章尾" in text
    assert count_tokens(text) <= 8000 + 200  # 允许少量标记开销


@pytest_asyncio.fixture
async def ctx_db(tmp_path, monkeypatch):
    db_path = tmp_path / "ctx.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("EMBEDDING_DIMS", "8")
    get_settings.cache_clear()
    db_mod.engine = None
    db_mod.SessionLocal = None
    llm_mod._client = None
    set_llm_client(MockLLMClient(embed_dim=8, smart=True))
    await init_db()
    yield
    await close_db()
    get_settings.cache_clear()
    llm_mod._client = None
    db_mod.engine = None
    db_mod.SessionLocal = None


@pytest.mark.asyncio
async def test_build_context_long_chapters_use_tails(ctx_db):
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="长章上下文", genre="玄幻", status="ready", chapter_count=2)
        session.add(novel)
        await session.flush()
        session.add_all(
            [
                Chapter(
                    novel_id=novel.id,
                    index=1,
                    title="第一章",
                    content="【章首1】" + "甲" * 12000 + "【章尾1】",
                    char_count=12008,
                    is_generated=False,
                ),
                Chapter(
                    novel_id=novel.id,
                    index=2,
                    title="第二章",
                    content="【章首2】" + "乙" * 12000 + "【章尾2】",
                    char_count=12008,
                    is_generated=False,
                ),
            ]
        )
        outline = Outline(
            novel_id=novel.id, title="大纲", status="confirmed", start_from_chapter=3
        )
        session.add(outline)
        await session.flush()
        item = OutlineItem(
            outline_id=outline.id,
            order=1,
            title="第三章",
            summary="续写",
            key_points=["推进"],
            status="pending",
        )
        session.add(item)
        await session.commit()
        ctx = await build_context(session, novel, item)
        assert "【章尾1】" in ctx.recent_chapters
        assert "【章尾2】" in ctx.recent_chapters
        assert "【章首1】" not in ctx.recent_chapters
        assert "【章首2】" not in ctx.recent_chapters
        # Story Bible 仍组装（可为空字符串），recent 不得撑爆总预算过多
        assert ctx.total_tokens < 40000
