"""大纲生成：异步任务 + 进度落库。"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.db import close_db, init_db
from app.llm.client import MockLLMClient, set_llm_client
from app.main import create_app
from app.models import AsyncTask, Novel, Outline
from app.services.outline import enqueue_outline_generate, outline_generate_handler
from app.services.tasks import get_task_queue
import app.db as db_mod


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    db_path = tmp_path / "outline_gen.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("EMBEDDING_DIMS", "8")
    get_settings.cache_clear()

    import app.services.tasks as tasks_mod
    import app.llm.client as llm_mod

    tasks_mod._queue = None
    llm_mod._client = None
    db_mod.engine = None
    db_mod.SessionLocal = None

    set_llm_client(MockLLMClient(embed_dim=8, smart=True))
    await init_db()
    queue = get_task_queue()
    queue.register("outline_generate", outline_generate_handler)
    app = create_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await close_db()
    get_settings.cache_clear()
    tasks_mod._queue = None
    llm_mod._client = None
    db_mod.engine = None
    db_mod.SessionLocal = None


async def _seed_novel() -> int:
    assert db_mod.SessionLocal
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="测大纲", genre="玄幻", status="ready", chapter_count=3)
        session.add(novel)
        await session.commit()
        return novel.id


@pytest.mark.asyncio
async def test_outline_generate_returns_task_id(client):
    novel_id = await _seed_novel()
    r = await client.post(
        f"/api/novels/{novel_id}/outlines/generate",
        json={"chapter_count": 2, "guidance": "先打怪"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "task_id" in body
    assert body["status"] in ("pending", "running", "completed")
    task_id = body["task_id"]

    await get_task_queue().wait_task(task_id, timeout=60)

    assert db_mod.SessionLocal
    async with db_mod.SessionLocal() as session:
        task = await session.get(AsyncTask, task_id)
        assert task is not None
        assert task.status == "completed"
        assert task.progress == 100.0
        assert task.task_type == "outline_generate"
        outline_id = (task.result or {}).get("outline_id")
        assert outline_id

        outline = await session.get(Outline, outline_id)
        assert outline is not None
        assert outline.novel_id == novel_id
        assert outline.status == "draft"

    r = await client.get(f"/api/novels/{novel_id}/outlines/{outline_id}")
    assert r.status_code == 200
    outline = r.json()
    assert len(outline["items"]) == 2
    assert outline["start_from_chapter"] == 4


@pytest.mark.asyncio
async def test_outline_generate_reaches_parse_progress(client):
    """大纲生成应顺利越过「解析并校正章号」进度，不因 database is locked 失败。"""
    novel_id = await _seed_novel()
    r = await client.post(
        f"/api/novels/{novel_id}/outlines/generate",
        json={"chapter_count": 2},
    )
    assert r.status_code == 200
    task_id = r.json()["task_id"]
    await get_task_queue().wait_task(task_id, timeout=60)

    assert db_mod.SessionLocal
    async with db_mod.SessionLocal() as session:
        task = await session.get(AsyncTask, task_id)
        assert task is not None
        assert task.status == "completed"
        assert task.error is None
        assert (task.result or {}).get("outline_id")


@pytest.mark.asyncio
async def test_outline_generate_service_enqueues(client):
    novel_id = await _seed_novel()
    assert db_mod.SessionLocal
    async with db_mod.SessionLocal() as session:
        task = await enqueue_outline_generate(session, novel_id, chapter_count=1)
        assert task.id is not None
        task_id = task.id

    await get_task_queue().wait_task(task_id, timeout=60)
    async with db_mod.SessionLocal() as session:
        task = await session.get(AsyncTask, task_id)
        assert task is not None
        assert task.status == "completed"
        assert (task.result or {}).get("outline_id")
