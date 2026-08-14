"""长章分段流式 vs 短章单次；max_tokens 随目标变化。"""

from __future__ import annotations

import pytest
import pytest_asyncio

from app.config import get_settings
from app.db import close_db, init_db
from app.llm.client import MockLLMClient, set_llm_client
from app.models import Novel, Outline, OutlineItem
from app.services.generation import stream_generate_chapter
import app.db as db_mod
import app.llm.client as llm_mod


@pytest_asyncio.fixture
async def db_ready(tmp_path, monkeypatch):
    db_path = tmp_path / "seg.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("EMBEDDING_DIMS", "8")
    monkeypatch.setenv("CHAPTER_SEGMENT_THRESHOLD", "4500")
    monkeypatch.setenv("SEGMENT_TARGET_CHARS", "3000")
    get_settings.cache_clear()
    db_mod.engine = None
    db_mod.SessionLocal = None
    llm_mod._client = None
    client = MockLLMClient(stream_text="叶凡踏入秘境继续前行。", embed_dim=8, smart=True)
    set_llm_client(client)
    await init_db()
    yield client
    await close_db()
    get_settings.cache_clear()
    llm_mod._client = None
    db_mod.engine = None
    db_mod.SessionLocal = None


async def _seed_item(session, *, title="测书"):
    novel = Novel(title=title, genre="玄幻", status="ready", chapter_count=0)
    session.add(novel)
    await session.flush()
    outline = Outline(
        novel_id=novel.id, title="大纲", status="confirmed", start_from_chapter=1
    )
    session.add(outline)
    await session.flush()
    item = OutlineItem(
        outline_id=outline.id,
        order=1,
        title="第一章 秘境",
        summary="叶凡进入秘境",
        key_points=["遇怪", "玉佩共鸣", "脱身"],
        status="pending",
    )
    session.add(item)
    await session.commit()
    return novel.id, item.id


@pytest.mark.asyncio
async def test_short_chapter_single_stream_with_scaled_max_tokens(db_ready):
    client = db_ready
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel_id, item_id = await _seed_item(session, title="短章")

    async with db_mod.SessionLocal() as session:
        events = [
            e
            async for e in stream_generate_chapter(
                session,
                novel_id,
                item_id,
                run_critic=False,
                max_critic_rounds=0,
                target_chars=3000,
            )
        ]
    assert not any(e.get("event") == "error" for e in events), events
    done = next(e for e in events if e.get("event") == "done")
    assert done.get("target_chars") == 3000
    assert done.get("segment_count") == 1
    assert len(client.stream_calls) == 1
    mt = client.stream_calls[0]["max_tokens"]
    assert mt != 6000
    assert 2000 <= mt <= 8000
    prompt = client.stream_calls[0]["messages"][-1]["content"]
    assert "本章目标约 3000 字" in prompt
    statuses = [e.get("message", "") for e in events if e.get("event") == "status"]
    assert not any("第 1/" in m and "段" in m for m in statuses)


@pytest.mark.asyncio
async def test_long_chapter_streams_multiple_segments(db_ready):
    client = db_ready
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel_id, item_id = await _seed_item(session, title="长章")

    async with db_mod.SessionLocal() as session:
        events = [
            e
            async for e in stream_generate_chapter(
                session,
                novel_id,
                item_id,
                run_critic=True,
                max_critic_rounds=2,
                target_chars=9000,
            )
        ]
    assert not any(e.get("event") == "error" for e in events), events
    done = next(e for e in events if e.get("event") == "done")
    assert done.get("target_chars") == 9000
    assert done.get("segment_count") == 3
    assert len(client.stream_calls) == 3
    statuses = [e.get("message", "") for e in events if e.get("event") == "status"]
    assert any("正在撰写第 1/3 段" in m for m in statuses)
    assert any("正在撰写第 3/3 段" in m for m in statuses)
    for call in client.stream_calls:
        assert 4000 <= call["max_tokens"] <= 8000
    first = client.stream_calls[0]["messages"][-1]["content"]
    last = client.stream_calls[-1]["messages"][-1]["content"]
    assert "不得过早收束" in first
    assert "本章完" in first
    assert "最后一段" in last or "本段为本章最后" in last
    # 长章即使请求 2 轮 Critic，也不整章重写
    assert done["consistency"] is not None
    assert done["consistency"]["critic_rounds"] == 0
    # 非首段 prompt 带已写结尾，而非把全文反复塞入
    mid = client.stream_calls[1]["messages"][-1]["content"]
    assert "已写正文" in mid or "已写" in mid
