"""成本汇总应对全部 CostLog 求和，而不是最近 200 行。"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.db import close_db, init_db
from app.llm.client import MockLLMClient, set_llm_client
from app.main import create_app
from app.models import CostLog, Novel
import app.db as db_mod


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    db_path = tmp_path / "costs.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    get_settings.cache_clear()

    import app.llm.client as llm_mod
    import app.services.tasks as tasks_mod

    db_mod.engine = None
    db_mod.SessionLocal = None
    llm_mod._client = None
    tasks_mod._queue = None
    set_llm_client(MockLLMClient(embed_dim=8))
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
async def test_cost_totals_include_more_than_200_rows(client):
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="成本", genre="玄幻", status="ready")
        session.add(novel)
        await session.flush()
        for _ in range(201):
            session.add(
                CostLog(
                    novel_id=novel.id,
                    purpose="embed",
                    provider="openai",
                    model="text-embedding-3-small",
                    input_tokens=10,
                    output_tokens=0,
                    cost_usd=1.0,
                )
            )
        await session.commit()
        novel_id = novel.id

    r = await client.get("/api/costs", params={"novel_id": novel_id})
    assert r.status_code == 200
    body = r.json()
    assert body["total_cost_usd"] == pytest.approx(201.0)
    assert body["total_input_tokens"] == 2010
    assert body["by_purpose"]["embed"] == pytest.approx(201.0)
    assert len(body["recent"]) <= 30
