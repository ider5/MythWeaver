"""小说 role：原稿可续写导出；参考只入库拆文风，不进入正文。"""

from __future__ import annotations

import json
import sqlite3

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.config import get_settings
from app.db import close_db, init_db
from app.llm.client import MockLLMClient, set_llm_client
from app.main import create_app
from app.models import Chapter, Novel
from app.services.novel_role import REFERENCE_EXPORT_DETAIL, REFERENCE_GENERATION_DETAIL
import app.db as db_mod

SAMPLE = """第一章 雨
街灯亮了。

第二章 门
他推开门。
"""


def _reset_runtime() -> None:
    import app.llm.client as llm_mod
    import app.services.tasks as tasks_mod

    db_mod.engine = None
    db_mod.SessionLocal = None
    llm_mod._client = None
    tasks_mod._queue = None


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    db_path = tmp_path / "role.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("EMBEDDING_DIMS", "8")
    get_settings.cache_clear()
    _reset_runtime()
    set_llm_client(MockLLMClient(embed_dim=8, smart=True))
    await init_db()
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await close_db()
    get_settings.cache_clear()
    _reset_runtime()


async def _preview(client: AsyncClient, title: str = "样例") -> str:
    files = {"file": ("sample.txt", SAMPLE.encode("utf-8"), "text/plain")}
    r = await client.post("/api/novels/import/preview", files=files, data={"title": title})
    assert r.status_code == 200, r.text
    return r.json()["import_token"]


async def _sse_events(resp) -> list[dict]:
    events: list[dict] = []
    async for line in resp.aiter_lines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


@pytest.mark.asyncio
async def test_import_defaults_to_manuscript_and_lists_by_role(client):
    token = await _preview(client, "原稿")
    r = await client.post(
        "/api/novels/import/confirm",
        json={"import_token": token, "title": "原稿", "genre": "玄幻"},
    )
    assert r.status_code == 200, r.text
    manuscript = r.json()
    assert manuscript["role"] == "manuscript"

    token = await _preview(client, "参考")
    r = await client.post(
        "/api/novels/import/confirm",
        json={"import_token": token, "title": "参考", "genre": "都市", "role": "reference"},
    )
    assert r.status_code == 200, r.text
    reference = r.json()
    assert reference["role"] == "reference"

    r = await client.post(
        "/api/novels/import/confirm",
        json={"import_token": "nope", "role": "sidequest"},
    )
    assert r.status_code == 422

    all_rows = (await client.get("/api/novels")).json()
    assert {n["title"] for n in all_rows} == {"原稿", "参考"}

    manuscripts = (await client.get("/api/novels", params={"role": "manuscript"})).json()
    assert [n["id"] for n in manuscripts] == [manuscript["id"]]

    references = (await client.get("/api/novels", params={"role": "reference"})).json()
    assert [n["id"] for n in references] == [reference["id"]]

    bad = await client.get("/api/novels", params={"role": "fanfic"})
    assert bad.status_code == 400

    created = await client.post("/api/novels", json={"title": "空原稿"})
    assert created.status_code == 200
    assert created.json()["role"] == "manuscript"

    patched = await client.patch(
        f"/api/novels/{manuscript['id']}",
        json={"role": "reference"},
    )
    assert patched.status_code == 200
    assert patched.json()["role"] == "reference"
    # 改回原稿，后面的导出用例另建数据
    back = await client.patch(
        f"/api/novels/{manuscript['id']}",
        json={"role": "manuscript"},
    )
    assert back.json()["role"] == "manuscript"


@pytest.mark.asyncio
async def test_reference_blocked_from_export_and_generation_but_ingestible(client):
    token = await _preview(client, "仿写")
    created = await client.post(
        "/api/novels/import/confirm",
        json={"import_token": token, "title": "仿写", "role": "reference"},
    )
    assert created.status_code == 200
    novel_id = created.json()["id"]

    exported = await client.get(f"/api/novels/{novel_id}/export")
    assert exported.status_code == 409
    assert exported.json()["detail"] == REFERENCE_EXPORT_DETAIL

    generated = await client.post(
        f"/api/novels/{novel_id}/generate",
        json={"outline_item_id": 1, "run_critic": False},
    )
    assert generated.status_code == 409
    assert generated.json()["detail"] == REFERENCE_GENERATION_DETAIL

    async with client.stream(
        "GET",
        f"/api/novels/{novel_id}/generate/stream",
        params={"outline_item_id": 1, "run_critic": False},
    ) as resp:
        assert resp.status_code == 200
        events = await _sse_events(resp)
    assert any(
        e.get("event") == "error" and REFERENCE_GENERATION_DETAIL in (e.get("message") or "")
        for e in events
    )
    assert not any(e.get("event") == "done" for e in events)

    detail = await client.get(f"/api/novels/{novel_id}")
    assert detail.json()["status"] == "imported"
    assert detail.json()["role"] == "reference"
    chapters = await client.get(f"/api/novels/{novel_id}/chapters")
    assert chapters.status_code == 200
    assert all(not c["is_generated"] for c in chapters.json())

    from app.services.ingestion import ingest_novel_handler
    from app.services.tasks import get_task_queue

    get_task_queue().register("ingest", ingest_novel_handler)
    started = await client.post(f"/api/novels/{novel_id}/ingest")
    assert started.status_code == 200, started.text
    task_id = started.json()["task_id"]
    await get_task_queue().wait_task(task_id, timeout=60)
    task = await client.get(f"/api/tasks/{task_id}")
    assert task.json()["status"] == "completed", task.text

    after = await client.get(f"/api/novels/{novel_id}")
    assert after.json()["role"] == "reference"
    assert after.json()["status"] == "ready"
    bible = await client.get(f"/api/novels/{novel_id}/bible")
    assert bible.status_code == 200
    assert len(bible.json()["characters"]) >= 1
    still_blocked = await client.get(f"/api/novels/{novel_id}/export")
    assert still_blocked.status_code == 409


@pytest.mark.asyncio
async def test_manuscript_export_and_generate_stream_still_open(client):
    token = await _preview(client, "正文")
    created = await client.post(
        "/api/novels/import/confirm",
        json={"import_token": token, "title": "正文", "role": "manuscript"},
    )
    novel_id = created.json()["id"]

    exported = await client.get(f"/api/novels/{novel_id}/export")
    assert exported.status_code == 200
    assert "第一章" in exported.content.decode("utf-8")

    async with client.stream(
        "GET",
        f"/api/novels/{novel_id}/generate/stream",
        params={"outline_item_id": 99999, "run_critic": False},
    ) as resp:
        assert resp.status_code == 200
        events = await _sse_events(resp)
    messages = [e.get("message") or "" for e in events if e.get("event") == "error"]
    assert messages
    assert all(REFERENCE_GENERATION_DETAIL not in m for m in messages)


@pytest.mark.asyncio
async def test_legacy_novels_gain_manuscript_role(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.db"
    raw = sqlite3.connect(db_path)
    raw.execute(
        """
        CREATE TABLE novels (
            id INTEGER PRIMARY KEY,
            title VARCHAR(256) NOT NULL,
            author VARCHAR(128),
            genre VARCHAR(64),
            description TEXT,
            source_path VARCHAR(512),
            status VARCHAR(32),
            total_chars INTEGER DEFAULT 0,
            chapter_count INTEGER DEFAULT 0,
            avg_chapter_chars INTEGER DEFAULT 0,
            median_chapter_chars INTEGER DEFAULT 0,
            created_at DATETIME,
            updated_at DATETIME
        )
        """
    )
    raw.execute(
        """
        INSERT INTO novels (
            title, genre, status, total_chars, chapter_count,
            avg_chapter_chars, median_chapter_chars, created_at, updated_at
        ) VALUES ('旧书', '玄幻', 'ready', 0, 0, 0, 0, '2026-01-01 00:00:00', '2026-01-01 00:00:00')
        """
    )
    raw.commit()
    raw.close()

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("EMBEDDING_DIMS", "8")
    get_settings.cache_clear()
    _reset_runtime()
    await init_db()
    try:
        assert db_mod.engine is not None
        async with db_mod.engine.connect() as conn:
            cols = (await conn.execute(text("PRAGMA table_info(novels)"))).fetchall()
        assert "role" in {row[1] for row in cols}

        assert db_mod.SessionLocal is not None
        async with db_mod.SessionLocal() as session:
            novel = await session.get(Novel, 1)
            assert novel is not None
            assert novel.role == "manuscript"
            generated = (
                await session.execute(select(Chapter).where(Chapter.novel_id == novel.id))
            ).scalars().all()
            assert generated == []
    finally:
        await close_db()
        get_settings.cache_clear()
        _reset_runtime()
