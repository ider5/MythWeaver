"""健康检查：数据库可读写、密钥是否配置、可选探测不回传密钥。"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.db import close_db, init_db
from app.main import create_app
from app.services.llm_profiles import reset_llm_profile_state
import app.db as db_mod


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    db_path = tmp_path / "health.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("EMBEDDING_DIMS", "8")
    monkeypatch.setenv("SUMMARY_API_KEY", "")
    monkeypatch.setenv("GENERATION_API_KEY", "")
    monkeypatch.setenv("EMBEDDING_API_KEY", "")
    get_settings.cache_clear()
    reset_llm_profile_state()

    import app.services.tasks as tasks_mod
    import app.llm.client as llm_mod

    tasks_mod._queue = None
    llm_mod._client = None
    db_mod.engine = None
    db_mod.SessionLocal = None

    await init_db()
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await close_db()
    reset_llm_profile_state()
    get_settings.cache_clear()
    tasks_mod._queue = None
    llm_mod._client = None
    db_mod.engine = None
    db_mod.SessionLocal = None


def _forbid_probe(**_kwargs):
    raise AssertionError("未请求探测时不应调用连接测试")


@pytest.mark.asyncio
async def test_health_reports_db_and_missing_key(client, monkeypatch):
    monkeypatch.setattr("app.services.health.test_connection", _forbid_probe)
    get_settings.cache_clear()

    r = await client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["app"] == "MythWeaver"
    assert body["ready"] is False
    assert body["first_run"] is True
    assert body["novel_count"] == 0
    assert body["checks"]["api"]["ok"] is True
    assert body["checks"]["db"]["ok"] is True
    assert body["checks"]["llm"]["configured"] is False
    assert body["checks"]["llm"]["probed"] is False
    assert body["checks"]["llm"]["ok"] is False
    stages = {row["stage"] for row in body["checks"]["llm"]["stages"]}
    assert stages == {"summary", "generation", "embedding"}
    assert "api_key" not in r.text


@pytest.mark.asyncio
async def test_health_placeholder_key_is_unconfigured(client, monkeypatch):
    monkeypatch.setenv("GENERATION_API_KEY", "sk-your-key")
    get_settings.cache_clear()
    monkeypatch.setattr("app.services.health.test_connection", _forbid_probe)

    r = await client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["checks"]["llm"]["configured"] is False


@pytest.mark.asyncio
async def test_health_configured_key_without_probe(client, monkeypatch):
    monkeypatch.setenv("GENERATION_API_KEY", "sk-test-health-secret")
    get_settings.cache_clear()
    monkeypatch.setattr("app.services.health.test_connection", _forbid_probe)

    r = await client.get("/api/health?probe=no")
    assert r.status_code == 200
    body = r.json()
    assert body["checks"]["llm"]["configured"] is True
    assert body["checks"]["llm"]["probed"] is False
    assert body["checks"]["llm"]["ok"] is True
    assert body["ready"] is True
    assert body["first_run"] is True
    assert "sk-test-health-secret" not in r.text


@pytest.mark.asyncio
async def test_health_probe_reuses_connection_test_and_scrubs_secret(client, monkeypatch):
    secret = "sk-test-health-secret"
    monkeypatch.setenv("GENERATION_API_KEY", secret)
    monkeypatch.setenv("GENERATION_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("GENERATION_MODEL", "demo-model")
    get_settings.cache_clear()

    async def fake_test_connection(**kwargs):
        assert kwargs["api_key"] == secret
        assert kwargs["base_url"] == "https://example.invalid/v1"
        assert kwargs["model"] == "demo-model"
        return {
            "ok": False,
            "error": f"rejected {secret}",
            "latency_ms": 12,
            "reply": None,
        }

    monkeypatch.setattr("app.services.health.test_connection", fake_test_connection)

    r = await client.get("/api/health", params={"probe": "llm"})
    assert r.status_code == 200
    body = r.json()
    llm = body["checks"]["llm"]
    assert llm["probed"] is True
    assert llm["ok"] is False
    assert llm["latency_ms"] == 12
    assert secret not in r.text
    assert "***" in llm["detail"]
    assert body["ready"] is False
    assert body["status"] == "ok"


@pytest.mark.asyncio
async def test_health_probe_success(client, monkeypatch):
    monkeypatch.setenv("GENERATION_API_KEY", "anonymous")
    get_settings.cache_clear()

    async def fake_test_connection(**_kwargs):
        return {"ok": True, "error": None, "latency_ms": 8, "reply": "ok"}

    monkeypatch.setattr("app.services.health.test_connection", fake_test_connection)
    r = await client.get("/api/health?probe=1")
    assert r.status_code == 200
    llm = r.json()["checks"]["llm"]
    assert llm["configured"] is True
    assert llm["probed"] is True
    assert llm["ok"] is True
    assert llm["reply"] == "ok"
    assert r.json()["ready"] is True


@pytest.mark.asyncio
async def test_health_novel_count_clears_first_run_when_key_exists(client, monkeypatch):
    monkeypatch.setenv("GENERATION_API_KEY", "sk-test-health-secret")
    get_settings.cache_clear()
    created = await client.post("/api/novels", json={"title": "空书架之外"})
    assert created.status_code == 200

    r = await client.get("/api/health")
    body = r.json()
    assert body["novel_count"] == 1
    assert body["first_run"] is False
    assert "sk-test-health-secret" not in r.text


@pytest.mark.asyncio
async def test_health_uses_active_profile_without_leaking_key(client, monkeypatch):
    secret = "sk-profile-health-secret"
    monkeypatch.setattr("app.services.health.test_connection", _forbid_probe)
    created = await client.post(
        "/api/providers/profiles",
        json={
            "name": "日常",
            "activate": True,
            "generation_base_url": "https://api.deepseek.com/v1",
            "generation_model": "deepseek-chat",
            "generation_api_key": secret,
            "embedding_base_url": "https://embed.example/v1",
            "embedding_model": "bge-m3",
            "embedding_api_key": "anonymous",
        },
    )
    assert created.status_code == 200

    r = await client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["checks"]["llm"]["configured"] is True
    assert "日常" in body["checks"]["llm"]["detail"]
    assert body["first_run"] is True
    assert secret not in r.text


@pytest.mark.asyncio
async def test_health_db_failure_is_degraded(client, monkeypatch):
    class _Broken:
        def __call__(self):
            return self

        async def __aenter__(self):
            raise RuntimeError("disk locked")

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(db_mod, "SessionLocal", _Broken())
    r = await client.get("/api/health")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert body["checks"]["api"]["ok"] is True
    assert body["checks"]["db"]["ok"] is False
    assert "disk locked" in body["checks"]["db"]["detail"]
    assert body["ready"] is False
    assert body["novel_count"] == 0
