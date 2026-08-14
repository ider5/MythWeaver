"""大纲删除：条目级联删除，章节正文保留并解绑 outline_item_id。"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.config import get_settings
from app.db import close_db, init_db
from app.llm.client import MockLLMClient, set_llm_client
from app.main import create_app
from app.models import Chapter, Novel, Outline, OutlineItem
import app.db as db_mod


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    db_path = tmp_path / "outline_del.db"
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
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await close_db()
    get_settings.cache_clear()
    llm_mod._client = None
    db_mod.engine = None
    db_mod.SessionLocal = None
    tasks_mod._queue = None


@pytest.mark.asyncio
async def test_delete_draft_outline(client):
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="删大纲", genre="玄幻", status="ready", chapter_count=3)
        session.add(novel)
        await session.flush()
        outline = Outline(
            novel_id=novel.id, title="草稿A", status="draft", start_from_chapter=4
        )
        session.add(outline)
        await session.flush()
        session.add(
            OutlineItem(
                outline_id=outline.id,
                order=1,
                title="第四章",
                summary="s",
                key_points=[],
                status="pending",
            )
        )
        await session.commit()
        novel_id = novel.id
        oid = outline.id

    r = await client.delete(f"/api/novels/{novel_id}/outlines/{oid}")
    assert r.status_code == 200
    body = r.json()
    assert body["outline_id"] == oid
    assert body["unbound_chapters"] == 0

    r = await client.get(f"/api/novels/{novel_id}/outlines")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_delete_confirmed_outline_unbinds_chapters(client):
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="确认大纲", genre="玄幻", status="ready", chapter_count=3)
        session.add(novel)
        await session.flush()
        outline = Outline(
            novel_id=novel.id,
            title="已确认",
            status="confirmed",
            start_from_chapter=4,
        )
        session.add(outline)
        await session.flush()
        item = OutlineItem(
            outline_id=outline.id,
            order=1,
            title="第四章：续",
            summary="s",
            key_points=["a"],
            status="done",
        )
        session.add(item)
        await session.flush()
        chapter = Chapter(
            novel_id=novel.id,
            index=4,
            title="第四章：续",
            content="已生成正文应保留",
            char_count=8,
            status="raw",
            is_generated=True,
            outline_item_id=item.id,
        )
        session.add(chapter)
        await session.commit()
        novel_id = novel.id
        oid = outline.id
        chapter_id = chapter.id
        item_id = item.id

    # 删除前可按 outline_item 取回章节
    r = await client.get(f"/api/novels/{novel_id}/chapters/by-outline-item/{item_id}")
    assert r.status_code == 200
    assert "应保留" in (r.json().get("content") or "")

    r = await client.delete(f"/api/novels/{novel_id}/outlines/{oid}")
    assert r.status_code == 200
    assert r.json()["unbound_chapters"] == 1

    async with db_mod.SessionLocal() as session:
        ch = await session.get(Chapter, chapter_id)
        assert ch is not None
        assert ch.content == "已生成正文应保留"
        assert ch.outline_item_id is None
        item_count = await session.scalar(
            select(func.count()).select_from(OutlineItem).where(OutlineItem.id == item_id)
        )
        assert item_count == 0
        outline_count = await session.scalar(
            select(func.count()).select_from(Outline).where(Outline.id == oid)
        )
        assert outline_count == 0

    r = await client.get(f"/api/novels/{novel_id}/chapters/by-outline-item/{item_id}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_chapter_by_outline_item_not_found(client):
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="空", genre="玄幻", status="ready")
        session.add(novel)
        await session.commit()
        novel_id = novel.id

    r = await client.get(f"/api/novels/{novel_id}/chapters/by-outline-item/99999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_chapter_by_outline_item_falls_back_by_index_and_rebinds(client):
    """outline_item_id 解绑后，仍可按目标章号回载，并重新绑定 FK。"""
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="解绑回退", genre="玄幻", status="ready", chapter_count=40)
        session.add(novel)
        await session.flush()
        outline = Outline(
            novel_id=novel.id,
            title="续写",
            status="confirmed",
            start_from_chapter=40,
        )
        session.add(outline)
        await session.flush()
        item = OutlineItem(
            outline_id=outline.id,
            order=1,
            title="第四十章：白发鬼手",
            summary="s",
            key_points=["a"],
            status="done",
        )
        session.add(item)
        await session.flush()
        chapter = Chapter(
            novel_id=novel.id,
            index=40,
            title="第四十章：白发鬼手",
            content="已生成但 outline_item_id 为空",
            char_count=14,
            status="embedded",
            is_generated=True,
            outline_item_id=None,  # 模拟解绑 / 旧数据
        )
        session.add(chapter)
        await session.commit()
        novel_id = novel.id
        item_id = item.id
        chapter_id = chapter.id

    r = await client.get(f"/api/novels/{novel_id}/chapters/by-outline-item/{item_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == chapter_id
    assert body["index"] == 40
    assert "outline_item_id 为空" in (body.get("content") or "")
    assert body["outline_item_id"] == item_id

    async with db_mod.SessionLocal() as session:
        ch = await session.get(Chapter, chapter_id)
        assert ch is not None
        assert ch.outline_item_id == item_id
