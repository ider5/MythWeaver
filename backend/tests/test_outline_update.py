"""大纲 PUT 按 id upsert，已绑定章节的 FK 不得被 SET NULL。"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.db import close_db, init_db
from app.llm.client import MockLLMClient, set_llm_client
from app.main import create_app
from app.models import Chapter, Novel, Outline, OutlineItem
import app.db as db_mod


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    db_path = tmp_path / "outline_upd.db"
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
    tasks_mod._queue = None
    db_mod.engine = None
    db_mod.SessionLocal = None


@pytest.mark.asyncio
async def test_outline_put_with_ids_keeps_item_id_and_chapter_fk(client):
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="改大纲", genre="玄幻", status="ready", chapter_count=1)
        session.add(novel)
        await session.flush()
        outline = Outline(
            novel_id=novel.id, title="续写", status="draft", start_from_chapter=2
        )
        session.add(outline)
        await session.flush()
        item = OutlineItem(
            outline_id=outline.id,
            order=1,
            title="第二章",
            summary="旧摘要",
            key_points=["旧"],
            status="done",
        )
        session.add(item)
        await session.flush()
        ch = Chapter(
            novel_id=novel.id,
            index=2,
            title="第二章",
            content="已生成正文",
            char_count=5,
            status="raw",
            is_generated=True,
            outline_item_id=item.id,
        )
        session.add(ch)
        await session.commit()
        novel_id = novel.id
        oid = outline.id
        item_id = item.id
        chapter_id = ch.id

    r = await client.put(
        f"/api/novels/{novel_id}/outlines/{oid}",
        json={
            "title": "续写（改）",
            "items": [
                {
                    "id": item_id,
                    "order": 1,
                    "title": "第二章 改名",
                    "summary": "新摘要",
                    "key_points": ["新"],
                    "status": "done",
                }
            ],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["items"][0]["id"] == item_id
    assert body["items"][0]["title"] == "第二章 改名"
    assert body["items"][0]["summary"] == "新摘要"
    assert body["items"][0]["status"] == "done"

    async with db_mod.SessionLocal() as session:
        ch = await session.get(Chapter, chapter_id)
        assert ch is not None
        assert ch.outline_item_id == item_id
