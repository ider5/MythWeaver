"""生成守卫：GET 参数校验、跨小说条目、客户端断开后复位 generating。"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import get_settings
from app.db import close_db, init_db
from app.llm.client import MockLLMClient, set_llm_client
from app.main import create_app
from app.models import AsyncTask, Chapter, Novel, Outline, OutlineItem
from app.services.generation import stream_generate_chapter
from app.services.tasks import fail_interrupted_tasks
import app.db as db_mod


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    db_path = tmp_path / "gen_guards.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("EMBEDDING_DIMS", "8")
    get_settings.cache_clear()

    import app.llm.client as llm_mod
    import app.services.tasks as tasks_mod

    db_mod.engine = None
    db_mod.SessionLocal = None
    llm_mod._client = None
    tasks_mod._queue = None
    set_llm_client(
        MockLLMClient(
            stream_text="叶凡拔剑。",
            embed_dim=8,
            smart=True,
            stream_chunk_delay=0.02,
        )
    )
    await init_db()
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await close_db()
    get_settings.cache_clear()
    llm_mod._client = None
    tasks_mod._queue = None
    db_mod.engine = None
    db_mod.SessionLocal = None


@pytest.mark.asyncio
async def test_get_stream_rejects_too_many_critic_rounds(client):
    r = await client.get(
        "/api/novels/1/generate/stream",
        params={"outline_item_id": 1, "max_critic_rounds": 99},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_stream_rejects_outline_item_from_other_novel(client):
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        a = Novel(title="甲", genre="玄幻", status="ready")
        b = Novel(title="乙", genre="玄幻", status="ready")
        session.add_all([a, b])
        await session.flush()
        outline = Outline(
            novel_id=b.id, title="乙大纲", status="confirmed", start_from_chapter=1
        )
        session.add(outline)
        await session.flush()
        item = OutlineItem(
            outline_id=outline.id,
            order=1,
            title="第一章",
            summary="s",
            key_points=[],
            status="pending",
        )
        session.add(item)
        await session.commit()
        a_id, item_id = a.id, item.id

    chunks = []
    async with client.stream(
        "GET",
        f"/api/novels/{a_id}/generate/stream",
        params={"outline_item_id": item_id, "run_critic": False},
    ) as resp:
        assert resp.status_code == 200
        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                chunks.append(__import__("json").loads(line[6:]))
    assert any(c.get("event") == "error" for c in chunks)
    assert not any(c.get("event") == "done" for c in chunks)


@pytest.mark.asyncio
async def test_client_disconnect_resets_generating_status(client):
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="断开", genre="玄幻", status="ready", chapter_count=0)
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
            title="第一章",
            summary="s",
            key_points=["打戏"],
            status="pending",
        )
        session.add(item)
        await session.commit()
        novel_id, item_id = novel.id, item.id

    async with db_mod.SessionLocal() as session:
        gen = stream_generate_chapter(
            session, novel_id, item_id, run_critic=False, max_critic_rounds=0
        )
        async for ev in gen:
            if ev.get("event") == "delta":
                await gen.aclose()
                break
        else:
            pytest.fail("未收到 delta，无法模拟断开")

    async with db_mod.SessionLocal() as session:
        item = await session.get(OutlineItem, item_id)
        novel = await session.get(Novel, novel_id)
        assert item is not None and novel is not None
        assert item.status == "pending"
        assert novel.status == "ready"


@pytest.mark.asyncio
async def test_fail_interrupted_tasks_marks_pending_and_running(client):
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        session.add(AsyncTask(task_type="ingest", status="pending", message="排队"))
        session.add(AsyncTask(task_type="ingest", status="running", message="执行中"))
        session.add(AsyncTask(task_type="ingest", status="completed", message="完成"))
        await session.commit()
        n = await fail_interrupted_tasks(session)

    assert n == 2
    async with db_mod.SessionLocal() as session:
        rows = (await session.execute(select(AsyncTask))).scalars().all()
        by_id = {t.id: t for t in rows}
        statuses = sorted(t.status for t in rows)
        assert statuses.count("failed") == 2
        assert statuses.count("completed") == 1
        failed = [t for t in rows if t.status == "failed"]
        assert all(t.error == "interrupted by restart" for t in failed)
        assert all(t.message == "进程重启，任务已中断" for t in failed)
        assert by_id  # 行仍在


@pytest.mark.asyncio
async def test_restart_keeps_chapter_draft(client):
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="草稿", genre="玄幻", status="generating", chapter_count=0)
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
            title="第一章",
            summary="s",
            key_points=["打戏"],
            status="generating",
        )
        session.add(item)
        await session.flush()
        text = "叶凡已经写下第一段。"
        chapter = Chapter(
            novel_id=novel.id,
            index=1,
            title="第一章",
            content=text,
            char_count=len(text),
            status="raw",
            is_generated=True,
            outline_item_id=item.id,
        )
        session.add(chapter)
        task = AsyncTask(
            novel_id=novel.id,
            task_type="batch_generate",
            status="running",
            message="正在生成第 1 章",
            result={"novel_id": novel.id, "items": []},
        )
        session.add(task)
        await session.commit()
        novel_id, item_id, chapter_id, task_id = novel.id, item.id, chapter.id, task.id
        changed = await fail_interrupted_tasks(session)

    assert changed == 3
    async with db_mod.SessionLocal() as session:
        saved = await session.get(Chapter, chapter_id)
        assert saved is not None
        assert saved.content == text
        item = await session.get(OutlineItem, item_id)
        assert item is not None and item.status == "pending"
        novel = await session.get(Novel, novel_id)
        assert novel is not None and novel.status == "ready"
        task = await session.get(AsyncTask, task_id)
        assert task is not None
        assert task.status == "failed"
        assert task.error == "interrupted by restart"
        assert "留下" in (task.message or "")
        assert task.result is not None
        assert task.result["recoverable_draft"] is True


async def _seed_items(session, *, count: int = 1) -> tuple[int, list[int]]:
    novel = Novel(title="并行", genre="玄幻", status="ready", chapter_count=0)
    session.add(novel)
    await session.flush()
    outline = Outline(
        novel_id=novel.id, title="大纲", status="confirmed", start_from_chapter=1
    )
    session.add(outline)
    await session.flush()
    item_ids: list[int] = []
    for order in range(1, count + 1):
        item = OutlineItem(
            outline_id=outline.id,
            order=order,
            title=f"第{order}章",
            summary="s",
            key_points=["打戏"],
            status="pending",
        )
        session.add(item)
        await session.flush()
        item_ids.append(item.id)
    await session.commit()
    return novel.id, item_ids


async def _collect(novel_id: int, item_id: int) -> list[dict]:
    assert db_mod.SessionLocal is not None
    events: list[dict] = []
    async with db_mod.SessionLocal() as session:
        async for ev in stream_generate_chapter(
            session, novel_id, item_id, run_critic=False, max_critic_rounds=0
        ):
            events.append(ev)
    return events


@pytest.mark.asyncio
async def test_concurrent_generation_allows_only_one(client):
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel_id, item_ids = await _seed_items(session, count=2)

    gate = MockLLMClient(stream_text="叶凡拔剑。", embed_dim=8, smart=True)

    started = asyncio.Event()
    release = asyncio.Event()
    original_stream = gate.stream

    async def gated_stream(*args, **kwargs):
        started.set()
        await release.wait()
        async for chunk in original_stream(*args, **kwargs):
            yield chunk

    gate.stream = gated_stream  # type: ignore[method-assign]
    set_llm_client(gate)

    first = asyncio.create_task(_collect(novel_id, item_ids[0]))
    await asyncio.wait_for(started.wait(), timeout=5)
    async with db_mod.SessionLocal() as session:
        visible = await session.get(Novel, novel_id)
        assert visible is not None and visible.status == "generating"

    second = asyncio.create_task(_collect(novel_id, item_ids[1]))
    # 必须在第一路还占着 generating 时就被拒绝，不能排到它写完再开始。
    second_events = await asyncio.wait_for(second, timeout=3)
    release.set()
    first_events = await asyncio.wait_for(first, timeout=10)

    assert any(ev.get("event") == "done" for ev in first_events)
    assert any(ev.get("message") == "已有生成进行中，请结束后再试" for ev in second_events)
    assert not any(ev.get("event") == "done" for ev in second_events)

    async with db_mod.SessionLocal() as session:
        novel = await session.get(Novel, novel_id)
        assert novel is not None and novel.status == "ready"
        winner = await session.get(OutlineItem, item_ids[0])
        loser = await session.get(OutlineItem, item_ids[1])
        assert winner is not None and winner.status == "done"
        assert loser is not None and loser.status == "pending"


@pytest.mark.asyncio
async def test_failed_generation_reset_does_not_clobber_next_claim(client):
    """错误事件交给调用方时，状态已经放开；调用方随后占用的锁不能被清掉。"""
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel_id, item_ids = await _seed_items(session, count=1)
    item_id = item_ids[0]
    set_llm_client(
        MockLLMClient(stream_text="叶凡。", embed_dim=8, smart=True, stream_error="模型崩了")
    )

    saw_error = False
    async with db_mod.SessionLocal() as session:
        async for ev in stream_generate_chapter(
            session, novel_id, item_id, run_critic=False, max_critic_rounds=0
        ):
            if ev.get("event") != "error":
                continue
            saw_error = True
            assert "模型崩了" in str(ev.get("message") or "")
            async with db_mod.SessionLocal() as other:
                novel = await other.get(Novel, novel_id)
                item = await other.get(OutlineItem, item_id)
                assert novel is not None and item is not None
                assert novel.status != "generating"
                assert item.status != "generating"
                novel.status = "generating"
                item.status = "generating"
                await other.commit()

    assert saw_error
    async with db_mod.SessionLocal() as session:
        novel = await session.get(Novel, novel_id)
        item = await session.get(OutlineItem, item_id)
        assert novel is not None and novel.status == "generating"
        assert item is not None and item.status == "generating"
