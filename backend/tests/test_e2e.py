"""端到端：导入→入库(mock)→大纲→生成→修订。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.db import close_db, init_db
from app.llm.client import MockLLMClient, set_llm_client
from app.main import create_app
from app.services.ingestion import ingest_novel_handler
from app.services.generation import revise_commit_handler
from app.services.outline import outline_generate_handler
from app.services.tasks import get_task_queue


SAMPLE_NOVEL = """第一章 晨光
少年叶凡醒来，怀中玉佩微微发热。

第二章 城门
叶凡抵达青阳城，遇见少女苏婉。

第三章 夜谈
苏婉透露城中有秘境将开。
"""


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("EMBEDDING_DIMS", "8")
    get_settings.cache_clear()

    # 重置单例，避免跨测试污染
    import app.services.tasks as tasks_mod
    import app.llm.client as llm_mod
    import app.db as db_mod

    tasks_mod._queue = None
    llm_mod._client = None
    db_mod.engine = None
    db_mod.SessionLocal = None

    set_llm_client(
        MockLLMClient(
            stream_text="第四章 秘境\n叶凡踏入青阳秘境，玉佩骤然发光。",
            embed_dim=8,
            smart=True,
        )
    )

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


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_e2e_flow(client):
    # 预览导入
    files = {"file": ("sample.txt", SAMPLE_NOVEL.encode("utf-8"), "text/plain")}
    r = await client.post("/api/novels/import/preview", files=files, data={"title": "试炼"})
    assert r.status_code == 200
    preview = r.json()
    assert preview["chapter_count"] >= 3
    token = preview["import_token"]

    # 确认
    r = await client.post(
        "/api/novels/import/confirm",
        json={"import_token": token, "title": "试炼", "genre": "玄幻"},
    )
    assert r.status_code == 200
    novel = r.json()
    novel_id = novel["id"]

    # 入库
    r = await client.post(f"/api/novels/{novel_id}/ingest")
    assert r.status_code == 200
    task_id = r.json()["task_id"]

    # 等待后台任务（ASGI 测试需显式 await create_task）
    await get_task_queue().wait_task(task_id, timeout=60)

    r = await client.get(f"/api/tasks/{task_id}")
    t = r.json()
    assert t["status"] == "completed", t

    # Story Bible
    r = await client.get(f"/api/novels/{novel_id}/bible")
    assert r.status_code == 200
    bible = r.json()
    assert len(bible["characters"]) >= 1

    # 大纲（异步任务）
    r = await client.post(
        f"/api/novels/{novel_id}/outlines/generate",
        json={"chapter_count": 1},
    )
    assert r.status_code == 200
    outline_task_id = r.json()["task_id"]
    await get_task_queue().wait_task(outline_task_id, timeout=60)
    r = await client.get(f"/api/tasks/{outline_task_id}")
    assert r.status_code == 200
    assert r.json()["status"] == "completed"
    outline_id = r.json()["result"]["outline_id"]
    r = await client.get(f"/api/novels/{novel_id}/outlines/{outline_id}")
    assert r.status_code == 200
    outline = r.json()
    item_id = outline["items"][0]["id"]
    r = await client.post(f"/api/novels/{novel_id}/outlines/{outline_id}/confirm")
    assert r.status_code == 200

    # 流式生成（收集 SSE）
    chunks = []
    async with client.stream(
        "GET",
        f"/api/novels/{novel_id}/generate/stream",
        params={"outline_item_id": item_id, "run_critic": True},
    ) as resp:
        assert resp.status_code == 200
        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                chunks.append(json.loads(line[6:]))
    done = next(c for c in chunks if c.get("event") == "done")
    chapter_id = done["chapter_id"]
    assert "秘境" in done["content"]

    # 修订入库
    r = await client.post(
        f"/api/novels/{novel_id}/chapters/{chapter_id}/revise",
        json={"content": done["content"] + "\n（人工微调）", "commit_to_knowledge": True},
    )
    assert r.status_code == 200
    assert r.json()["version_type"] == "user_edited"
    task_id = r.json()["task_id"]
    assert task_id
    await get_task_queue().wait_task(task_id, timeout=60)
    r = await client.get(f"/api/tasks/{task_id}")
    assert r.status_code == 200
    assert r.json()["status"] == "completed"

    # 成本
    r = await client.get("/api/costs", params={"novel_id": novel_id})
    assert r.status_code == 200
    assert r.json()["total_input_tokens"] >= 0
