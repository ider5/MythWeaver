"""LLM 命名配置：增删改、启用，以及密钥只回掩码。"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.db import close_db, init_db
from app.llm.client import LLMClient
from app.main import create_app
from app.services.llm_profiles import key_view, reload_active_profile, reset_llm_profile_state
import app.db as db_mod

ENV_GEN_KEY = "sk-env-SECRET1234"
ENV_SUM_KEY = "sk-env-SUMKEY5678"
ENV_EMB_KEY = "sk-env-EMBKEY4321"
LOCAL_KEY = "sk-local-PROFILE9999"


def test_key_view_masks_secret():
    view = key_view(ENV_GEN_KEY)
    assert view == {"mode": "keyed", "mask": "••••1234"}
    assert ENV_GEN_KEY not in (view["mask"] or "")
    assert key_view("anonymous") == {"mode": "anonymous", "mask": None}
    assert key_view("")["mode"] == "anonymous"
    assert key_view("sk-your-generation-key")["mode"] == "anonymous"


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    db_path = tmp_path / "profiles.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("GENERATION_PROVIDER", "openai")
    monkeypatch.setenv("GENERATION_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("GENERATION_API_KEY", ENV_GEN_KEY)
    monkeypatch.setenv("GENERATION_MODEL", "env-gen-model")
    monkeypatch.setenv("SUMMARY_PROVIDER", "openai")
    monkeypatch.setenv("SUMMARY_BASE_URL", "https://summary.example/v1")
    monkeypatch.setenv("SUMMARY_API_KEY", ENV_SUM_KEY)
    monkeypatch.setenv("SUMMARY_MODEL", "env-sum-model")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://embed.example/v1")
    monkeypatch.setenv("EMBEDDING_API_KEY", ENV_EMB_KEY)
    monkeypatch.setenv("EMBEDDING_MODEL", "env-embed-model")
    get_settings.cache_clear()
    reset_llm_profile_state()
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
    db_mod.engine = None
    db_mod.SessionLocal = None


def _assert_no_secrets(text: str) -> None:
    for secret in (ENV_GEN_KEY, ENV_SUM_KEY, ENV_EMB_KEY, LOCAL_KEY):
        assert secret not in text
    assert "api_key" not in text


@pytest.mark.asyncio
async def test_profile_crud_activate_and_mask(client):
    active = await client.get("/api/providers/active")
    assert active.status_code == 200
    body = active.json()
    assert body["source"] == "env"
    assert body["generation_model"] == "env-gen-model"
    assert body["generation_key"]["mode"] == "keyed"
    assert body["generation_key"]["mask"] == "••••1234"
    assert body["summary_follows_generation"] is False
    _assert_no_secrets(active.text)

    created = await client.post(
        "/api/providers/profiles",
        json={"name": "日常", "from_current": True, "activate": True},
    )
    assert created.status_code == 200
    saved = created.json()
    assert saved["is_active"] is True
    assert saved["generation_model"] == "env-gen-model"
    assert saved["summary_model"] == "env-sum-model"
    assert saved["embedding_model"] == "env-embed-model"
    assert saved["generation_key"]["mask"] == "••••1234"
    assert saved["embedding_key"]["mask"] == "••••4321"
    _assert_no_secrets(created.text)

    from app.services.llm_profiles import effective_llm

    endpoint = LLMClient().generation_endpoint()
    assert endpoint.model == "env-gen-model"
    assert endpoint.api_key == ENV_GEN_KEY
    assert endpoint.base_url == "https://env.example/v1"
    summary = LLMClient().summary_endpoint()
    assert summary.model == "env-sum-model"
    assert summary.api_key == ENV_SUM_KEY
    assert ENV_GEN_KEY not in repr(effective_llm())

    cfg = await client.get("/api/config")
    assert cfg.json()["generation_model"] == "env-gen-model"
    assert cfg.json()["summary_model"] == "env-sum-model"
    assert cfg.json()["embedding_model"] == "env-embed-model"

    local = await client.post(
        "/api/providers/profiles",
        json={
            "name": "本地",
            "vendor_id": "ollama",
            "generation_base_url": "http://127.0.0.1:11434/v1",
            "generation_model": "llama3.2",
            "generation_api_key": "anonymous",
            "embedding_base_url": "http://127.0.0.1:11434/v1",
            "embedding_model": "nomic-embed",
            "embedding_api_key": "",
            "summary_follows_generation": True,
        },
    )
    assert local.status_code == 200
    local_id = local.json()["id"]
    assert local.json()["generation_key"]["mode"] == "anonymous"
    assert local.json()["is_active"] is False
    _assert_no_secrets(local.text)

    renamed = await client.patch(f"/api/providers/profiles/{local_id}", json={"name": "本地 Ollama"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "本地 Ollama"

    listed = await client.get("/api/providers/profiles")
    assert listed.status_code == 200
    names = [row["name"] for row in listed.json()["profiles"]]
    assert names == ["日常", "本地 Ollama"]
    _assert_no_secrets(listed.text)

    switched = await client.post(f"/api/providers/profiles/{local_id}/activate")
    assert switched.status_code == 200
    assert switched.json()["is_active"] is True
    assert LLMClient().generation_endpoint().model == "llama3.2"
    assert LLMClient().generation_endpoint().api_key == "anonymous"
    assert LLMClient().summary_endpoint().model == "llama3.2"
    active_local = await client.get("/api/providers/active")
    assert active_local.json()["source"] == "profile"
    assert active_local.json()["profile_name"] == "本地 Ollama"
    assert active_local.json()["generation_key"]["mode"] == "anonymous"
    assert (await client.get("/api/config")).json()["generation_model"] == "llama3.2"

    daily_id = saved["id"]
    copied = await client.post(f"/api/providers/profiles/{daily_id}/update-from-current")
    assert copied.status_code == 200
    assert copied.json()["generation_model"] == "llama3.2"
    assert copied.json()["generation_key"]["mode"] == "anonymous"
    assert copied.json()["is_active"] is False
    _assert_no_secrets(copied.text)
    # 正在生效的仍是本地，直到再次启用「日常」
    assert LLMClient().generation_endpoint().model == "llama3.2"

    reset_llm_profile_state()
    assert LLMClient().generation_endpoint().model == "env-gen-model"
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        await reload_active_profile(session)
    assert LLMClient().generation_endpoint().model == "llama3.2"
    assert LLMClient().generation_endpoint().api_key == "anonymous"

    removed = await client.delete(f"/api/providers/profiles/{local_id}")
    assert removed.status_code == 200
    after = await client.get("/api/providers/active")
    assert after.json()["source"] == "env"
    assert after.json()["profile_id"] is None
    assert LLMClient().generation_endpoint().model == "env-gen-model"
    assert LLMClient().generation_endpoint().api_key == ENV_GEN_KEY


@pytest.mark.asyncio
async def test_profile_errors_and_key_keep(client):
    first = await client.post(
        "/api/providers/profiles",
        json={
            "name": "甲",
            "generation_base_url": "https://api.deepseek.com/v1",
            "generation_model": "deepseek-chat",
            "generation_api_key": LOCAL_KEY,
            "embedding_base_url": "https://embed.example/v1",
            "embedding_model": "env-embed-model",
        },
    )
    assert first.status_code == 200
    profile_id = first.json()["id"]
    _assert_no_secrets(first.text)

    dup = await client.post(
        "/api/providers/profiles",
        json={"name": "甲", "from_current": True},
    )
    assert dup.status_code == 409

    missing = await client.post(
        "/api/providers/profiles",
        json={"name": "缺地址", "generation_model": "x"},
    )
    assert missing.status_code == 400

    missing_id = await client.post("/api/providers/profiles/9999/activate")
    assert missing_id.status_code == 404

    kept = await client.patch(
        f"/api/providers/profiles/{profile_id}",
        json={"generation_model": "deepseek-reasoner"},
    )
    assert kept.status_code == 200
    assert kept.json()["generation_model"] == "deepseek-reasoner"
    assert kept.json()["generation_key"]["mask"] == "••••9999"

    cleared = await client.patch(
        f"/api/providers/profiles/{profile_id}",
        json={"generation_api_key": ""},
    )
    assert cleared.status_code == 200
    assert cleared.json()["generation_key"]["mode"] == "anonymous"

    turned_on = await client.post(f"/api/providers/profiles/{profile_id}/activate")
    assert turned_on.status_code == 200
    assert LLMClient().generation_endpoint().api_key == ""
    assert LLMClient().generation_endpoint().model == "deepseek-reasoner"
