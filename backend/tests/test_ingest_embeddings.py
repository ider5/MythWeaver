"""入库完成后每章必须写入 embedding，不能因 identity map 停在 raw 而跳过。"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.config import get_settings
from app.db import close_db, init_db, is_vec_available
from app.llm.client import MockLLMClient, set_llm_client
from app.models import AsyncTask, Chapter, Novel
from app.services.ingestion import ingest_novel_handler
from app.services.tasks import TaskProgress
import app.db as db_mod


@pytest_asyncio.fixture
async def db_ready(tmp_path, monkeypatch):
    db_path = tmp_path / "ingest_embed.db"
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
    set_llm_client(MockLLMClient(embed_dim=8, smart=True))
    await init_db()
    yield
    await close_db()
    get_settings.cache_clear()
    llm_mod._client = None
    tasks_mod._queue = None
    db_mod.engine = None
    db_mod.SessionLocal = None


@pytest.mark.asyncio
async def test_ingest_writes_embeddings_despite_stale_identity_map(db_ready):
    """摘要/抽取在独立 session 提交后，外层任务 session 仍应批量向量化。"""
    assert db_mod.SessionLocal is not None
    dims = get_settings().embedding_dims

    async with db_mod.SessionLocal() as session:
        novel = Novel(title="向量入库", genre="玄幻", status="imported", chapter_count=2)
        session.add(novel)
        await session.flush()
        session.add_all(
            [
                Chapter(
                    novel_id=novel.id,
                    index=1,
                    title="第一章",
                    content="少年叶凡醒来，怀中玉佩微微发热。",
                    char_count=16,
                    status="raw",
                ),
                Chapter(
                    novel_id=novel.id,
                    index=2,
                    title="第二章",
                    content="叶凡抵达青阳城，遇见少女苏婉。",
                    char_count=16,
                    status="raw",
                ),
            ]
        )
        task = AsyncTask(
            novel_id=novel.id,
            task_type="ingest",
            status="running",
            message="入库中",
        )
        session.add(task)
        await session.commit()
        novel_id = novel.id
        task_id = task.id

        # 先把 Chapter 读进 identity map（与 handler 内 select 同路径）
        loaded = (
            await session.execute(select(Chapter).where(Chapter.novel_id == novel_id))
        ).scalars().all()
        assert all(ch.status == "raw" for ch in loaded)

        await ingest_novel_handler(session, task, TaskProgress(task_id))

    async with db_mod.SessionLocal() as session:
        chapters = (
            await session.execute(
                select(Chapter).where(Chapter.novel_id == novel_id).order_by(Chapter.index)
            )
        ).scalars().all()
        assert len(chapters) == 2
        for ch in chapters:
            assert ch.status == "embedded", (ch.index, ch.status, bool(ch.embedding_json))
            assert ch.embedding_json is not None
            assert len(ch.embedding_json) == dims
        novel = await session.get(Novel, novel_id)
        assert novel is not None
        assert novel.status == "ready"
        if is_vec_available():
            n_vec = (
                await session.execute(text("SELECT count(*) FROM chapter_embeddings"))
            ).scalar_one()
            assert int(n_vec) == 2
