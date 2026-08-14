"""连续续写：未修订入库时，下一章上下文仍须包含刚写完的上一章。"""

from __future__ import annotations

import pytest
import pytest_asyncio

from app.config import get_settings
from app.db import close_db, init_db
from app.llm.client import MockLLMClient, get_llm_client, set_llm_client
from app.models import Chapter, Novel, Outline, OutlineItem
from app.services.generation import stream_generate_chapter
import app.db as db_mod


@pytest_asyncio.fixture
async def db_ready(tmp_path, monkeypatch):
    db_path = tmp_path / "gen_ctx.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("EMBEDDING_DIMS", "8")
    get_settings.cache_clear()

    import app.llm.client as llm_mod

    db_mod.engine = None
    db_mod.SessionLocal = None
    llm_mod._client = None
    set_llm_client(
        MockLLMClient(
            stream_text="第二章锚点BBB叶凡踏入青阳秘境。",
            embed_dim=8,
            smart=True,
        )
    )
    await init_db()
    yield
    await close_db()
    get_settings.cache_clear()
    llm_mod._client = None
    db_mod.engine = None
    db_mod.SessionLocal = None


async def _drain(session, novel_id: int, item_id: int) -> list[dict]:
    events = []
    async for evt in stream_generate_chapter(
        session,
        novel_id,
        item_id,
        run_critic=False,
        max_critic_rounds=0,
    ):
        events.append(evt)
    return events


@pytest.mark.asyncio
async def test_next_chapter_context_includes_uncommitted_previous(db_ready):
    """chapter_count 未随生成更新时，下一章 prompt 仍应带上刚写的上一章。"""
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(
            title="连续续写",
            genre="玄幻",
            status="ready",
            chapter_count=1,
        )
        session.add(novel)
        await session.flush()
        session.add(
            Chapter(
                novel_id=novel.id,
                index=1,
                title="第一章",
                content="第一章原文锚点AAA叶凡醒来。",
                char_count=14,
                status="embedded",
                is_generated=False,
            )
        )
        outline = Outline(
            novel_id=novel.id,
            title="续写",
            status="confirmed",
            start_from_chapter=2,
        )
        session.add(outline)
        await session.flush()
        item1 = OutlineItem(
            outline_id=outline.id,
            order=1,
            title="第二章",
            summary="入秘境",
            key_points=["入秘境"],
            status="pending",
        )
        item2 = OutlineItem(
            outline_id=outline.id,
            order=2,
            title="第三章",
            summary="遇险",
            key_points=["遇险"],
            status="pending",
        )
        session.add_all([item1, item2])
        await session.commit()
        novel_id = novel.id
        item1_id = item1.id
        item2_id = item2.id

    async with db_mod.SessionLocal() as session:
        events = await _drain(session, novel_id, item1_id)
        assert not any(e.get("event") == "error" for e in events), events

    mock = get_llm_client()
    mock.stream_calls.clear()
    mock.stream_text = "第三章锚点CCC叶凡拔剑。"

    async with db_mod.SessionLocal() as session:
        novel = await session.get(Novel, novel_id)
        assert novel is not None
        assert novel.chapter_count == 1  # 生成成功不更新 chapter_count
        events = await _drain(session, novel_id, item2_id)
        assert not any(e.get("event") == "error" for e in events), events

    blobs = ["\n".join(m["content"] for m in call["messages"]) for call in mock.stream_calls]
    assert blobs, "第二轮生成应调用 stream"
    joined = "\n".join(blobs)
    assert "第二章锚点BBB" in joined
