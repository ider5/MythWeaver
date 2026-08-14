"""修订入库：同步落版本 + 异步增量任务进度。"""

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
from app.models import AsyncTask, Chapter, ChapterVersion, Novel, Summary
from app.services.generation import enqueue_revise_commit, revise_and_commit, revise_commit_handler
from app.services.ingestion import incremental_update_chapter, ingest_novel_handler
from app.services.tasks import TaskProgress, get_task_queue
import app.db as db_mod


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    db_path = tmp_path / "revise.db"
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

    set_llm_client(MockLLMClient(stream_text="修订后的正文", embed_dim=8, smart=True))
    await init_db()
    queue = get_task_queue()
    queue.register("ingest", ingest_novel_handler)
    queue.register("revise_commit", revise_commit_handler)
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


async def _seed_chapter(*, total_chars: int = 4) -> tuple[int, int]:
    assert db_mod.SessionLocal
    async with db_mod.SessionLocal() as session:
        novel = Novel(
            title="测修订",
            genre="玄幻",
            status="ready",
            chapter_count=1,
            total_chars=total_chars,
        )
        session.add(novel)
        await session.flush()
        ch = Chapter(
            novel_id=novel.id,
            index=1,
            title="第一章",
            content="原稿内容",
            char_count=4,
            status="embedded",
            is_generated=True,
        )
        session.add(ch)
        await session.flush()
        ver = ChapterVersion(
            chapter_id=ch.id,
            version_type="generated",
            content="原稿内容",
        )
        session.add(ver)
        session.add(
            Summary(
                novel_id=novel.id,
                chapter_id=ch.id,
                level="chapter",
                content="旧摘要",
            )
        )
        await session.commit()
        return novel.id, ch.id


@pytest.mark.asyncio
async def test_revise_without_commit_returns_no_task(client):
    novel_id, chapter_id = await _seed_chapter()
    r = await client.post(
        f"/api/novels/{novel_id}/chapters/{chapter_id}/revise",
        json={"content": "仅保存版本", "commit_to_knowledge": False},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["version_type"] == "user_edited"
    assert body["content"] == "仅保存版本"
    assert body["task_id"] is None


@pytest.mark.asyncio
async def test_revise_and_commit_async_progress(client):
    novel_id, chapter_id = await _seed_chapter()
    r = await client.post(
        f"/api/novels/{novel_id}/chapters/{chapter_id}/revise",
        json={"content": "修订后的正文，含新情节。", "commit_to_knowledge": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["version_type"] == "user_edited"
    assert body["task_id"] is not None
    task_id = body["task_id"]

    await get_task_queue().wait_task(task_id, timeout=60)

    assert db_mod.SessionLocal
    async with db_mod.SessionLocal() as session:
        task = await session.get(AsyncTask, task_id)
        assert task is not None
        assert task.status == "completed"
        assert task.progress == 100.0
        assert task.task_type == "revise_commit"
        assert (task.result or {}).get("chapter_id") == chapter_id

        ch = await session.get(Chapter, chapter_id)
        assert ch is not None
        assert ch.content.startswith("修订后的正文")
        assert ch.status == "embedded"

        versions = (
            await session.execute(
                select(ChapterVersion)
                .where(ChapterVersion.chapter_id == chapter_id)
                .order_by(ChapterVersion.id)
            )
        ).scalars().all()
        assert len(versions) == 2
        assert versions[-1].version_type == "user_edited"

        summary = (
            await session.execute(
                select(Summary).where(Summary.chapter_id == chapter_id, Summary.level == "chapter")
            )
        ).scalar_one_or_none()
        assert summary is not None


@pytest.mark.asyncio
async def test_revise_and_commit_service_enqueues(db_ready_queue):
    """服务层返回 task_id 且不阻塞等待入库完成。"""
    novel_id, chapter_id = await _seed_chapter()
    assert db_mod.SessionLocal
    async with db_mod.SessionLocal() as session:
        ver, task_id = await revise_and_commit(
            session, chapter_id, "服务层修订", commit_to_knowledge=True
        )
        assert ver.version_type == "user_edited"
        assert task_id is not None

    await get_task_queue().wait_task(task_id, timeout=60)
    async with db_mod.SessionLocal() as session:
        task = await session.get(AsyncTask, task_id)
        assert task is not None
        assert task.status == "completed"


@pytest.mark.asyncio
async def test_commit_knowledge_no_new_version(client):
    """重试入库只入队，不新建 user_edited 版本。"""
    novel_id, chapter_id = await _seed_chapter()
    # 先正常修订一次，产生 user_edited
    r1 = await client.post(
        f"/api/novels/{novel_id}/chapters/{chapter_id}/revise",
        json={"content": "已修订正文", "commit_to_knowledge": False},
    )
    assert r1.status_code == 200
    version_id = r1.json()["id"]

    assert db_mod.SessionLocal
    async with db_mod.SessionLocal() as session:
        before = (
            await session.execute(
                select(ChapterVersion).where(ChapterVersion.chapter_id == chapter_id)
            )
        ).scalars().all()
        assert len(before) == 2

    r2 = await client.post(f"/api/novels/{novel_id}/chapters/{chapter_id}/commit-knowledge")
    assert r2.status_code == 200
    body = r2.json()
    assert body["chapter_id"] == chapter_id
    assert body["task_id"] is not None
    assert body["version_id"] == version_id

    await get_task_queue().wait_task(body["task_id"], timeout=60)

    async with db_mod.SessionLocal() as session:
        after = (
            await session.execute(
                select(ChapterVersion)
                .where(ChapterVersion.chapter_id == chapter_id)
                .order_by(ChapterVersion.id)
            )
        ).scalars().all()
        assert len(after) == 2
        assert after[-1].id == version_id
        assert after[-1].version_type == "user_edited"
        task = await session.get(AsyncTask, body["task_id"])
        assert task is not None
        assert task.status == "completed"
        assert task.task_type == "revise_commit"


@pytest.mark.asyncio
async def test_progress_update_does_not_commit_business_txn(db_ready_queue):
    """进度更新使用独立 session，业务侧删除可被 rollback；持锁时不抛错。"""
    novel_id, chapter_id = await _seed_chapter()
    assert db_mod.SessionLocal

    async with db_mod.SessionLocal() as session:
        task = AsyncTask(
            novel_id=novel_id,
            task_type="revise_commit",
            status="running",
            progress=0.0,
            message="测试",
            result={"chapter_id": chapter_id},
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        task_id = task.id

    progress = TaskProgress(task_id)
    q = progress.subscribe()

    async with db_mod.SessionLocal() as session:
        old = (
            await session.execute(
                select(Summary).where(Summary.chapter_id == chapter_id, Summary.level == "chapter")
            )
        ).scalars().all()
        assert len(old) == 1
        for s in old:
            await session.delete(s)
        await session.flush()

        # 业务持写锁时：不得提交删除，也不得因 locked 抛错；SSE 仍应收到进度
        await progress.update(session, progress=15.0, message="生成章节摘要…")
        evt = await asyncio.wait_for(q.get(), timeout=2)
        assert evt["progress"] == 15.0
        assert evt["message"] == "生成章节摘要…"

        await session.rollback()

    async with db_mod.SessionLocal() as session:
        restored = (
            await session.execute(
                select(Summary).where(Summary.chapter_id == chapter_id, Summary.level == "chapter")
            )
        ).scalars().all()
        assert len(restored) == 1
        assert restored[0].content == "旧摘要"

    # 无锁时进度可正常落库
    await progress.update(None, progress=42.0, message="无锁落库")
    async with db_mod.SessionLocal() as session:
        task = await session.get(AsyncTask, task_id)
        assert task is not None
        assert task.progress == 42.0
        assert task.message == "无锁落库"


@pytest.mark.asyncio
async def test_progress_under_write_lock_does_not_raise(db_ready_queue):
    """复现 database is locked：业务 flush 后立刻独立 UPDATE 进度，应软跳过。"""
    novel_id, chapter_id = await _seed_chapter()
    assert db_mod.SessionLocal

    async with db_mod.SessionLocal() as session:
        task = AsyncTask(
            novel_id=novel_id,
            task_type="outline_generate",
            status="running",
            progress=18.0,
            message="正在生成大纲…",
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        task_id = task.id

    progress = TaskProgress(task_id)
    async with db_mod.SessionLocal() as session:
        from app.llm.cost_tracker import log_cost

        await log_cost(
            session,
            purpose="outline",
            provider="mock",
            model="mock",
            input_tokens=1,
            output_tokens=1,
            novel_id=novel_id,
        )
        # 此时写锁未释放；旧逻辑会在此 database is locked
        await progress.update(session, progress=72.0, message="解析并校正章号…")
        assert progress._last["progress"] == 72.0
        assert progress._last["message"] == "解析并校正章号…"
        await session.commit()


@pytest.mark.asyncio
async def test_incremental_update_total_chars_idempotent(db_ready_queue):
    """重复增量入库按章重算 total_chars，不重复累加。"""
    novel_id, chapter_id = await _seed_chapter(total_chars=4)
    assert db_mod.SessionLocal

    async with db_mod.SessionLocal() as session:
        ch = await session.get(Chapter, chapter_id)
        assert ch is not None
        ch.content = "修订后更长的正文内容ABC"
        ch.char_count = 12
        await session.commit()

    async with db_mod.SessionLocal() as session:
        ch = await session.get(Chapter, chapter_id)
        assert ch is not None
        await incremental_update_chapter(session, ch)

    async with db_mod.SessionLocal() as session:
        novel = await session.get(Novel, novel_id)
        assert novel is not None
        assert novel.total_chars == 12
        ch = await session.get(Chapter, chapter_id)
        assert ch is not None
        await incremental_update_chapter(session, ch)

    async with db_mod.SessionLocal() as session:
        novel = await session.get(Novel, novel_id)
        assert novel is not None
        assert novel.total_chars == 12


@pytest.mark.asyncio
async def test_enqueue_revise_commit_service(db_ready_queue):
    novel_id, chapter_id = await _seed_chapter()
    assert db_mod.SessionLocal
    async with db_mod.SessionLocal() as session:
        task_id = await enqueue_revise_commit(session, chapter_id)
        assert task_id is not None
        versions = (
            await session.execute(
                select(ChapterVersion).where(ChapterVersion.chapter_id == chapter_id)
            )
        ).scalars().all()
        assert len(versions) == 1

    await get_task_queue().wait_task(task_id, timeout=60)
    async with db_mod.SessionLocal() as session:
        task = await session.get(AsyncTask, task_id)
        assert task is not None
        assert task.status == "completed"
        versions = (
            await session.execute(
                select(ChapterVersion).where(ChapterVersion.chapter_id == chapter_id)
            )
        ).scalars().all()
        assert len(versions) == 1


@pytest_asyncio.fixture
async def db_ready_queue(tmp_path, monkeypatch):
    db_path = tmp_path / "revise_svc.db"
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
    queue.register("revise_commit", revise_commit_handler)
    yield
    await close_db()
    get_settings.cache_clear()
    tasks_mod._queue = None
    llm_mod._client = None
    db_mod.engine = None
    db_mod.SessionLocal = None
