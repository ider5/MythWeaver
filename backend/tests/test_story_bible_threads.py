"""伏笔章节可写入、可清空；省略字段不会误清。"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.db import close_db, init_db
from app.main import create_app
from app.models import Novel
import app.db as db_mod


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    db_path = tmp_path / "bible.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    get_settings.cache_clear()

    import app.services.tasks as tasks_mod
    import app.llm.client as llm_mod

    db_mod.engine = None
    db_mod.SessionLocal = None
    tasks_mod._queue = None
    llm_mod._client = None
    await init_db()
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


@pytest.mark.asyncio
async def test_plot_thread_chapters_set_clear_and_relationships_roundtrip(client):
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="时间线", genre="玄幻", status="ready", chapter_count=20)
        session.add(novel)
        await session.commit()
        novel_id = novel.id

    created = await client.post(
        f"/api/novels/{novel_id}/bible/plot-threads",
        json={
            "title": "玉佩之谜",
            "description": "发热",
            "thread_type": "伏笔",
            "status": "未回收",
            "introduced_chapter": 2,
        },
    )
    assert created.status_code == 200
    tid = created.json()["id"]
    assert created.json()["introduced_chapter"] == 2
    assert created.json()["resolved_chapter"] is None

    patched = await client.patch(
        f"/api/novels/{novel_id}/bible/plot-threads/{tid}",
        json={"resolved_chapter": 11, "status": "已回收"},
    )
    assert patched.status_code == 200
    assert patched.json()["introduced_chapter"] == 2
    assert patched.json()["resolved_chapter"] == 11

    status_only = await client.patch(
        f"/api/novels/{novel_id}/bible/plot-threads/{tid}",
        json={"status": "未回收"},
    )
    assert status_only.status_code == 200
    assert status_only.json()["introduced_chapter"] == 2
    assert status_only.json()["resolved_chapter"] == 11

    cleared = await client.patch(
        f"/api/novels/{novel_id}/bible/plot-threads/{tid}",
        json={"resolved_chapter": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["resolved_chapter"] is None
    assert cleared.json()["introduced_chapter"] == 2

    char = await client.post(
        f"/api/novels/{novel_id}/bible/characters",
        json={"name": "叶凡", "role": "主角", "relationships": {"苏婉": "青梅竹马"}},
    )
    assert char.status_code == 200

    bible = await client.get(f"/api/novels/{novel_id}/bible")
    assert bible.status_code == 200
    body = bible.json()
    assert body["plot_threads"][0]["introduced_chapter"] == 2
    assert body["plot_threads"][0]["resolved_chapter"] is None
    assert body["characters"][0]["relationships"]["苏婉"] == "青梅竹马"
