"""连续生成：mock LLM 写两章，Critic 未通过时停下。"""

from __future__ import annotations

import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import get_settings
from app.db import close_db, init_db
from app.llm.client import MockLLMClient, set_llm_client
from app.main import create_app
from app.models import AsyncTask, Chapter, Novel, Outline, OutlineItem
from app.services.batch_generation import batch_generate_handler
from app.services.tasks import get_task_queue
import app.db as db_mod


class _CriticGateFailClient(MockLLMClient):
    def _smart_response(self, messages):
        blob = "\n".join(m.get("content", "") for m in messages)
        if "修订编辑" in blob:
            return "叶凡按剑立在城门口，夜风掀起衣角，他没有进门。"
        if "审查员" in blob or "一致性" in blob:
            return json.dumps(
                {
                    "ok": False,
                    "issues": [
                        {
                            "type": "continuity",
                            "severity": "error",
                            "message": "人物行为与设定冲突",
                            "detail": "门禁",
                        }
                    ],
                },
                ensure_ascii=False,
            )
        return super()._smart_response(messages)


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    db_path = tmp_path / "batch.db"
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

    set_llm_client(
        MockLLMClient(
            stream_text="叶凡踏入青阳秘境，玉佩骤然发光。",
            embed_dim=8,
            smart=True,
        )
    )
    await init_db()
    get_task_queue().register("batch_generate", batch_generate_handler)
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


async def _seed(*, confirmed: bool = True, orders: tuple[int, ...] = (1, 2)) -> tuple[int, int]:
    assert db_mod.SessionLocal
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="批测", genre="玄幻", status="ready", chapter_count=0)
        session.add(novel)
        await session.flush()
        outline = Outline(
            novel_id=novel.id,
            title="已确认大纲",
            status="confirmed" if confirmed else "draft",
            start_from_chapter=1,
        )
        session.add(outline)
        await session.flush()
        for order in orders:
            session.add(
                OutlineItem(
                    outline_id=outline.id,
                    order=order,
                    title=f"第{order}节",
                    summary="向前走",
                    key_points=["打戏"],
                    status="pending",
                )
            )
        await session.commit()
        return novel.id, outline.id


@pytest.mark.asyncio
async def test_batch_generates_two_chapters(client):
    novel_id, outline_id = await _seed()
    response = await client.post(
        f"/api/novels/{novel_id}/generate/batch",
        json={
            "outline_id": outline_id,
            "from_order": 1,
            "count": 2,
            "run_critic": True,
        },
    )
    assert response.status_code == 200, response.text
    task_id = response.json()["task_id"]
    await get_task_queue().wait_task(task_id, timeout=60)

    assert db_mod.SessionLocal
    async with db_mod.SessionLocal() as session:
        task = await session.get(AsyncTask, task_id)
        assert task is not None
        assert task.status == "completed", task.error
        assert task.result is not None
        assert task.result["paused"] is False
        assert task.result["count"] == 2
        assert [row["status"] for row in task.result["items"]] == ["done", "done"]
        chapters = (
            await session.execute(
                select(Chapter).where(Chapter.novel_id == novel_id).order_by(Chapter.index)
            )
        ).scalars().all()
        assert len(chapters) == 2
        assert all(chapter.is_generated for chapter in chapters)
        assert "秘境" in chapters[0].content
        assert "秘境" in chapters[1].content


@pytest.mark.asyncio
async def test_batch_pauses_when_critic_fails(client):
    set_llm_client(
        _CriticGateFailClient(
            stream_text="叶凡踏入青阳秘境，玉佩骤然发光。",
            embed_dim=8,
            smart=True,
        )
    )
    novel_id, outline_id = await _seed()
    response = await client.post(
        f"/api/novels/{novel_id}/generate/batch",
        json={"outline_id": outline_id, "from_order": 1, "count": 2, "run_critic": True},
    )
    assert response.status_code == 200, response.text
    task_id = response.json()["task_id"]
    await get_task_queue().wait_task(task_id, timeout=60)

    assert db_mod.SessionLocal
    async with db_mod.SessionLocal() as session:
        task = await session.get(AsyncTask, task_id)
        assert task is not None
        assert task.status == "completed", task.error
        assert task.result["paused"] is True
        assert task.result["items"][0]["status"] == "paused"
        assert task.result["items"][1]["status"] == "blocked"
        chapters = (
            await session.execute(select(Chapter).where(Chapter.novel_id == novel_id))
        ).scalars().all()
        assert len(chapters) == 1


@pytest.mark.asyncio
async def test_batch_rejects_draft_outline_and_bad_range(client):
    novel_id, outline_id = await _seed(confirmed=False)
    draft = await client.post(
        f"/api/novels/{novel_id}/generate/batch",
        json={"outline_id": outline_id, "from_order": 1, "count": 2, "run_critic": False},
    )
    assert draft.status_code == 400

    novel_id, outline_id = await _seed(orders=(1, 3))
    gap = await client.post(
        f"/api/novels/{novel_id}/generate/batch",
        json={"outline_id": outline_id, "from_order": 1, "count": 2, "run_critic": False},
    )
    assert gap.status_code == 400

    too_many = await client.post(
        f"/api/novels/{novel_id}/generate/batch",
        json={"outline_id": outline_id, "from_order": 1, "count": 11, "run_critic": False},
    )
    assert too_many.status_code == 422

    novel_id, outline_id = await _seed()
    assert db_mod.SessionLocal
    async with db_mod.SessionLocal() as session:
        novel = await session.get(Novel, novel_id)
        assert novel is not None
        novel.role = "reference"
        await session.commit()
    reference = await client.post(
        f"/api/novels/{novel_id}/generate/batch",
        json={"outline_id": outline_id, "from_order": 1, "count": 2, "run_critic": False},
    )
    assert reference.status_code == 409
