"""任务取消与失败重试。"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.db import close_db, init_db
from app.llm.client import MockLLMClient, set_llm_client
from app.main import create_app
from app.models import AsyncTask, Novel
from app.services.generation import revise_commit_handler
from app.services.ingestion import ingest_novel_handler
from app.services.outline import outline_generate_handler
from app.services.tasks import get_task_queue
import app.db as db_mod


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    db_path = tmp_path / "tasks.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("EMBEDDING_DIMS", "8")
    get_settings.cache_clear()

    import app.llm.client as llm_mod
    import app.services.tasks as tasks_mod

    tasks_mod._queue = None
    llm_mod._client = None
    db_mod.engine = None
    db_mod.SessionLocal = None

    set_llm_client(MockLLMClient(embed_dim=8, smart=True))
    await init_db()
    queue = get_task_queue()
    queue.register("ingest", ingest_novel_handler)
    queue.register("revise_commit", revise_commit_handler)
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


async def _novel(*, status: str = "imported") -> int:
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="任务", genre="玄幻", status=status)
        session.add(novel)
        await session.commit()
        return novel.id


async def _add_task(**kwargs) -> int:
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        task = AsyncTask(**kwargs)
        session.add(task)
        await session.commit()
        return task.id


@pytest.mark.asyncio
async def test_cancel_pending_task_and_release_novel(client):
    novel_id = await _novel(status="ingesting")
    task_id = await _add_task(
        novel_id=novel_id,
        task_type="ingest",
        status="pending",
        message="入库排队中",
    )

    r = await client.post(f"/api/tasks/{task_id}/cancel")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "cancelled"
    assert body["message"] == "已取消"
    assert body["recoverable"] is True

    again = await client.post(f"/api/tasks/{task_id}/cancel")
    assert again.status_code == 200
    assert again.json()["status"] == "cancelled"

    novel = await client.get(f"/api/novels/{novel_id}")
    assert novel.status_code == 200
    assert novel.json()["status"] == "imported"


@pytest.mark.asyncio
async def test_cancel_running_task_stops_handler(client):
    await client.get("/api/health")
    novel_id = await _novel()
    started = asyncio.Event()

    async def slow(session, task, progress):
        await progress.update(session, progress=20.0, message="工作中")
        started.set()
        for _ in range(40):
            progress.raise_if_cancelled()
            await asyncio.sleep(0.05)
        return {"done": True}

    get_task_queue().register("ingest", slow)
    created = await client.post(f"/api/novels/{novel_id}/ingest")
    assert created.status_code == 200
    task_id = created.json()["task_id"]

    await asyncio.wait_for(started.wait(), timeout=5)
    cancelled = await client.post(f"/api/tasks/{task_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] in ("running", "pending", "cancelled")

    await get_task_queue().wait_task(task_id, timeout=5)
    final = await client.get(f"/api/tasks/{task_id}")
    assert final.status_code == 200
    body = final.json()
    assert body["status"] == "cancelled"
    assert body["message"] == "已取消"
    assert body["error"] in (None, "")
    assert not (body.get("result") or {}).get("done")
    assert body["recoverable"] is True

    novel = await client.get(f"/api/novels/{novel_id}")
    assert novel.json()["status"] == "imported"


@pytest.mark.asyncio
async def test_cancel_rejects_finished_and_missing(client):
    task_id = await _add_task(task_type="ingest", status="completed", message="完成", progress=100)
    done = await client.post(f"/api/tasks/{task_id}/cancel")
    assert done.status_code == 409

    failed_id = await _add_task(task_type="ingest", status="failed", message="失败", error="x")
    failed = await client.post(f"/api/tasks/{failed_id}/cancel")
    assert failed.status_code == 409

    missing = await client.post("/api/tasks/99999/cancel")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_failed_ingest_is_recoverable_and_retry_requeues(client):
    novel_id = await _novel()
    task_id = await _add_task(
        novel_id=novel_id,
        task_type="ingest",
        status="failed",
        message="失败",
        error="boom",
        progress=100,
    )

    listed = await client.get("/api/tasks", params={"novel_id": novel_id})
    assert listed.status_code == 200
    row = listed.json()[0]
    assert row["id"] == task_id
    assert row["recoverable"] is True

    retried = await client.post(f"/api/tasks/{task_id}/retry")
    assert retried.status_code == 200
    new_id = retried.json()["id"]
    assert new_id != task_id
    assert retried.json()["task_type"] == "ingest"
    assert retried.json()["status"] in ("pending", "running", "completed")

    await get_task_queue().wait_task(new_id, timeout=10)
    final = await client.get(f"/api/tasks/{new_id}")
    assert final.json()["status"] == "completed"
    novel = await client.get(f"/api/novels/{novel_id}")
    assert novel.json()["status"] == "ready"

    again = await client.post(f"/api/tasks/{new_id}/retry")
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_handler_failure_marks_retryable_message(client):
    await client.get("/api/health")
    novel_id = await _novel()

    async def boom(session, task, progress):
        await progress.update(session, progress=5.0, message="开始")
        raise RuntimeError("boom")

    get_task_queue().register("ingest", boom)
    created = await client.post(f"/api/novels/{novel_id}/ingest")
    task_id = created.json()["task_id"]
    await get_task_queue().wait_task(task_id, timeout=5)

    body = (await client.get(f"/api/tasks/{task_id}")).json()
    assert body["status"] == "failed"
    assert body["message"] == "失败，可重试"
    assert "boom" in (body["error"] or "")
    assert body["recoverable"] is True
    novel = await client.get(f"/api/novels/{novel_id}")
    assert novel.json()["status"] == "imported"


@pytest.mark.asyncio
async def test_retry_blocked_while_ingest_running_and_unknown_type(client):
    await client.get("/api/health")
    novel_id = await _novel()
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow(session, task, progress):
        started.set()
        await release.wait()
        return {"ok": True}

    failed_id = await _add_task(
        novel_id=novel_id,
        task_type="ingest",
        status="failed",
        message="失败",
        error="x",
    )
    unknown_id = await _add_task(task_type="other", status="failed", message="失败", error="x")

    get_task_queue().register("ingest", slow)
    created = await client.post(f"/api/novels/{novel_id}/ingest")
    running_id = created.json()["task_id"]
    await asyncio.wait_for(started.wait(), timeout=5)

    blocked = await client.post(f"/api/tasks/{failed_id}/retry")
    assert blocked.status_code == 409
    unknown = await client.post(f"/api/tasks/{unknown_id}/retry")
    assert unknown.status_code == 409

    release.set()
    await get_task_queue().wait_task(running_id, timeout=5)


@pytest.mark.asyncio
async def test_duplicate_ingest_rejected(client):
    await client.get("/api/health")
    novel_id = await _novel()
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow(session, task, progress):
        started.set()
        await release.wait()
        return {"ok": True}

    get_task_queue().register("ingest", slow)
    first = await client.post(f"/api/novels/{novel_id}/ingest")
    assert first.status_code == 200
    task_id = first.json()["task_id"]
    await asyncio.wait_for(started.wait(), timeout=5)

    second = await client.post(f"/api/novels/{novel_id}/ingest")
    assert second.status_code == 409
    assert "进行中" in second.json()["detail"]

    release.set()
    await get_task_queue().wait_task(task_id, timeout=5)
