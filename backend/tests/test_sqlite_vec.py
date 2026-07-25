"""sqlite-vec 加载、vec0 写入与近邻检索。"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.config import get_settings
from app.db import close_db, init_db, is_vec_available
from app.llm.client import MockLLMClient, set_llm_client
from app.models import Chapter, Novel
from app.services.retrieval import (
    backfill_vec_from_json,
    embed_and_store_batch,
    hybrid_search,
    serialize_vec,
    upsert_chapter_embedding,
)


@pytest_asyncio.fixture
async def db_session(tmp_path, monkeypatch):
    db_path = tmp_path / "vec.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("EMBEDDING_DIMS", "8")
    monkeypatch.setenv("EMBEDDING_BATCH_SIZE", "4")
    get_settings.cache_clear()

    import app.db as db_mod
    import app.llm.client as llm_mod

    db_mod.engine = None
    db_mod.SessionLocal = None
    llm_mod._client = None
    set_llm_client(MockLLMClient(embed_dim=8))

    await init_db()
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        yield session
    await close_db()
    get_settings.cache_clear()
    llm_mod._client = None


@pytest.mark.asyncio
async def test_sqlite_vec_loads_without_warning(db_session, caplog):
    import logging

    assert is_vec_available() is True
    # 启动路径不应残留「加载失败」warning
    warnings = [
        r
        for r in caplog.records
        if r.levelno >= logging.WARNING and "sqlite-vec 加载失败" in r.getMessage()
    ]
    assert warnings == []

    ver = (await db_session.execute(text("SELECT vec_version()"))).fetchone()
    assert ver is not None
    assert str(ver[0]).startswith("v")


@pytest.mark.asyncio
async def test_vec0_upsert_and_knn_search(db_session):
    assert is_vec_available()

    novel = Novel(title="向量测试", genre="玄幻", status="ready")
    db_session.add(novel)
    await db_session.flush()

    chapters = []
    vectors = [
        [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        [0.9, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    ]
    for i, vec in enumerate(vectors, start=1):
        ch = Chapter(
            novel_id=novel.id,
            index=i,
            title=f"第{i}章",
            content=f"内容{i}",
            char_count=10,
            status="embedded",
        )
        db_session.add(ch)
        await db_session.flush()
        await upsert_chapter_embedding(db_session, ch, vec)
        chapters.append(ch)
    await db_session.commit()

    count = (
        await db_session.execute(text("SELECT count(*) FROM chapter_embeddings"))
    ).scalar_one()
    assert count == 3

    # 直接 KNN
    q = serialize_vec(vectors[0])
    rows = (
        await db_session.execute(
            text(
                """
                SELECT ve.chapter_id, ve.distance
                FROM chapter_embeddings AS ve
                JOIN chapters AS c ON c.id = ve.chapter_id
                WHERE c.novel_id = :nid AND ve.embedding MATCH :emb AND k = 2
                """
            ),
            {"nid": novel.id, "emb": q},
        )
    ).fetchall()
    assert len(rows) == 2
    assert rows[0][0] == chapters[0].id
    assert float(rows[0][1]) == pytest.approx(0.0, abs=1e-5)


@pytest.mark.asyncio
async def test_backfill_from_json(db_session):
    assert is_vec_available()
    novel = Novel(title="回填", genre="玄幻", status="ready")
    db_session.add(novel)
    await db_session.flush()

    vec = [0.5, 0.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    ch = Chapter(
        novel_id=novel.id,
        index=1,
        title="仅 JSON",
        content="hello",
        char_count=5,
        status="embedded",
        embedding_json=vec,
    )
    db_session.add(ch)
    await db_session.commit()

    # 确认 vec0 尚无数据
    n0 = (
        await db_session.execute(text("SELECT count(*) FROM chapter_embeddings"))
    ).scalar_one()
    assert n0 == 0

    written = await backfill_vec_from_json(db_session)
    await db_session.commit()
    assert written == 1
    n1 = (
        await db_session.execute(text("SELECT count(*) FROM chapter_embeddings"))
    ).scalar_one()
    assert n1 == 1

    # 幂等
    assert await backfill_vec_from_json(db_session) == 0


@pytest.mark.asyncio
async def test_hybrid_search_uses_vec(db_session):
    assert is_vec_available()
    novel = Novel(title="检索", genre="玄幻", status="ready")
    db_session.add(novel)
    await db_session.flush()

    # Mock embed 对相同文本稳定；用 upsert 写入已知向量后再搜
    ch_near = Chapter(
        novel_id=novel.id, index=1, title="近邻", content="玉佩发热", status="embedded"
    )
    ch_far = Chapter(
        novel_id=novel.id, index=2, title="远邻", content="城门相遇", status="embedded"
    )
    db_session.add_all([ch_near, ch_far])
    await db_session.flush()

    # 让 mock 向量与 query 的 hash 对齐：先 embed query 得到 qvec，再写入
    client = MockLLMClient(embed_dim=8)
    qvecs, _ = await client.embed(["玉佩"])
    other, _ = await client.embed(["完全无关的城池描写xyz"])
    await upsert_chapter_embedding(db_session, ch_near, qvecs[0])
    await upsert_chapter_embedding(db_session, ch_far, other[0])
    await db_session.commit()

    set_llm_client(client)
    hits = await hybrid_search(db_session, novel.id, "玉佩", top_k=2)
    assert hits
    assert hits[0][0].id == ch_near.id


@pytest.mark.asyncio
async def test_batch_embed_store(db_session):
    novel = Novel(title="批量", genre="玄幻", status="ready")
    db_session.add(novel)
    await db_session.flush()
    chapters = []
    for i in range(5):
        ch = Chapter(
            novel_id=novel.id,
            index=i + 1,
            title=f"第{i+1}章",
            content=f"文本{i}",
            status="extracted",
        )
        db_session.add(ch)
        chapters.append(ch)
    await db_session.flush()

    items = [(ch, ch.content) for ch in chapters]
    written = await embed_and_store_batch(db_session, items, novel_id=novel.id)
    await db_session.commit()
    assert written == 5

    refreshed = (
        await db_session.execute(select(Chapter).where(Chapter.novel_id == novel.id))
    ).scalars().all()
    assert all(ch.embedding_json and len(ch.embedding_json) == 8 for ch in refreshed)

    if is_vec_available():
        n = (
            await db_session.execute(text("SELECT count(*) FROM chapter_embeddings"))
        ).scalar_one()
        assert n == 5
