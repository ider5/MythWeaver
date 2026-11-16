"""从零开书：前提 → Story Bible 种子 → 大纲 → 开篇，不要求原稿。"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import get_settings
from app.db import close_db, init_db
from app.llm.client import MockLLMClient, get_llm_client, set_llm_client
from app.main import create_app
from app.models import AsyncTask, Chapter, Character
from app.services.batch_generation import batch_generate_handler
from app.services.outline import outline_generate_handler
from app.services.tasks import get_task_queue
import app.db as db_mod

PREMISE = "边城少年捡到一枚会发热的铜钱，必须在七日内找到失主。"
STYLE = "短句冷叙述"


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    db_path = tmp_path / "scratch.db"
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
    set_llm_client(
        MockLLMClient(
            stream_text=(
                "叶凡踏入青阳秘境，铜钱骤然发热。"
                + "夜风穿过石门，他按剑前行，灯火在身后一盏盏灭掉。" * 120
                + "地图背面写着苏婉的名字。"
            ),
            embed_dim=8,
            smart=True,
        )
    )
    await init_db()
    queue = get_task_queue()
    queue.register("outline_generate", outline_generate_handler)
    queue.register("batch_generate", batch_generate_handler)
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
async def test_scratch_loop_writes_opening_without_manuscript(client):
    created = await client.post(
        "/api/novels/scratch",
        json={
            "title": "铜钱",
            "genre": "玄幻",
            "premise": PREMISE,
            "writing_style": STYLE,
        },
    )
    assert created.status_code == 200, created.text
    novel = created.json()
    novel_id = novel["id"]
    assert novel["origin"] == "scratch"
    assert novel["status"] == "blank"
    assert novel["role"] == "manuscript"
    assert novel["chapter_count"] == 0
    assert novel["premise"] == PREMISE
    assert novel["writing_style"] == STYLE

    chapters = await client.get(f"/api/novels/{novel_id}/chapters")
    assert chapters.status_code == 200
    assert chapters.json() == []

    blocked = await client.post(f"/api/novels/{novel_id}/ingest")
    assert blocked.status_code == 409
    still = await client.get(f"/api/novels/{novel_id}")
    assert still.json()["status"] == "blank"

    seeded = await client.post(f"/api/novels/{novel_id}/scratch/seed")
    assert seeded.status_code == 200, seeded.text
    seed_body = seeded.json()
    assert seed_body["novel"]["status"] == "seeded"
    assert any(row["name"] == "叶凡" for row in seed_body["characters"])
    assert seed_body["world_settings"]
    assert seed_body["plot_threads"]

    again = await client.post(f"/api/novels/{novel_id}/scratch/seed")
    assert again.status_code == 200, again.text
    bible = await client.get(f"/api/novels/{novel_id}/bible")
    names = [row["name"] for row in bible.json()["characters"]]
    assert names.count("叶凡") == 1

    outlined = await client.post(
        f"/api/novels/{novel_id}/outlines/generate",
        json={"chapter_count": 2},
    )
    assert outlined.status_code == 200, outlined.text
    task_id = outlined.json()["task_id"]
    await get_task_queue().wait_task(task_id, timeout=60)
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        task = await session.get(AsyncTask, task_id)
        assert task is not None
        assert task.status == "completed", task.error
        outline_id = (task.result or {}).get("outline_id")
    assert outline_id

    outline = await client.get(f"/api/novels/{novel_id}/outlines/{outline_id}")
    assert outline.status_code == 200, outline.text
    outline_body = outline.json()
    assert outline_body["start_from_chapter"] == 1
    assert len(outline_body["items"]) == 2
    assert "第一章" in outline_body["items"][0]["title"]

    confirmed = await client.post(f"/api/novels/{novel_id}/outlines/{outline_id}/confirm")
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "confirmed"

    batch = await client.post(
        f"/api/novels/{novel_id}/generate/batch",
        json={
            "outline_id": outline_id,
            "from_order": 1,
            "count": 2,
            "run_critic": True,
        },
    )
    assert batch.status_code == 200, batch.text
    batch_id = batch.json()["task_id"]
    await get_task_queue().wait_task(batch_id, timeout=60)
    async with db_mod.SessionLocal() as session:
        task = await session.get(AsyncTask, batch_id)
        assert task is not None
        assert task.status == "completed", task.error
        assert task.result is not None
        assert task.result["paused"] is False
        chapters = (
            await session.execute(
                select(Chapter).where(Chapter.novel_id == novel_id).order_by(Chapter.index)
            )
        ).scalars().all()
        assert [chapter.index for chapter in chapters] == [1, 2]
        assert all(chapter.is_generated for chapter in chapters)
        assert "铜钱" in chapters[0].content
        people = (
            await session.execute(select(Character).where(Character.novel_id == novel_id))
        ).scalars().all()
        assert any(person.name == "叶凡" for person in people)

    detail = await client.get(f"/api/novels/{novel_id}")
    assert detail.json()["origin"] == "scratch"
    assert detail.json()["chapter_count"] == 2
    assert detail.json()["status"] == "ready"

    exported = await client.get(f"/api/novels/{novel_id}/export")
    assert exported.status_code == 200
    assert "铜钱" in exported.text

    blobs = [
        "\n".join(message["content"] for message in call["messages"])
        for call in get_llm_client().stream_calls
    ]
    assert blobs
    joined = "\n".join(blobs)
    assert PREMISE in joined
    assert STYLE in joined
    assert "没有导入原稿" in joined

    listed = await client.get("/api/novels", params={"origin": "scratch"})
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [novel_id]


@pytest.mark.asyncio
async def test_import_create_is_not_scratch_and_cannot_seed(client):
    created = await client.post("/api/novels", json={"title": "手工"})
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["origin"] == "import"
    assert body["status"] == "imported"
    seeded = await client.post(f"/api/novels/{body['id']}/scratch/seed")
    assert seeded.status_code == 409
    bad = await client.get("/api/novels", params={"origin": "fanfic"})
    assert bad.status_code == 400


@pytest.mark.asyncio
async def test_scratch_create_rejects_short_premise(client):
    response = await client.post(
        "/api/novels/scratch",
        json={"title": "空", "premise": "太短", "writing_style": "冷"},
    )
    assert response.status_code == 422
