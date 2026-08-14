"""生成守卫：GET 参数校验、跨小说条目、客户端断开后复位 generating。"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import get_settings
from app.db import close_db, init_db
from app.llm.client import MockLLMClient, set_llm_client
from app.main import create_app
from app.models import AsyncTask, Novel, Outline, OutlineItem
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
        assert by_id  # 行仍在
