"""厂商预设与连接测试单元测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.services.providers import list_presets, resolve_connection


def test_list_presets_contains_core_vendors():
    ids = {p["id"] for p in list_presets()}
    assert "openai" in ids
    assert "deepseek" in ids
    assert "custom" in ids
    for p in list_presets():
        assert "base_url" in p
        assert "default_model" in p


def test_resolve_connection_from_preset():
    url, model = resolve_connection(vendor_id="deepseek", base_url=None, model=None)
    assert "deepseek" in url
    assert model == "deepseek-chat"


def test_resolve_connection_override():
    url, model = resolve_connection(
        vendor_id="openai",
        base_url="https://example.com/v1/",
        model="my-model",
    )
    assert url == "https://example.com/v1"
    assert model == "my-model"


def test_resolve_connection_missing_raises():
    with pytest.raises(ValueError):
        resolve_connection(vendor_id="custom", base_url=None, model=None)


@pytest.mark.asyncio
async def test_get_presets_api():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/providers")
    assert r.status_code == 200
    data = r.json()
    assert "presets" in data
    assert len(data["presets"]) >= 5


@pytest.mark.asyncio
async def test_post_test_connection_ok():
    fake_msg = MagicMock()
    fake_msg.content = "ok"
    fake_choice = MagicMock()
    fake_choice.message = fake_msg
    fake_resp = MagicMock()
    fake_resp.choices = [fake_choice]

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=fake_resp)
    mock_client.close = AsyncMock()

    app = create_app()
    transport = ASGITransport(app=app)
    with patch("app.services.providers.AsyncOpenAI", return_value=mock_client):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/api/providers/test",
                json={"vendor_id": "openai", "api_key": "sk-test"},
            )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["model"] == "gpt-4o-mini"
    assert body["error"] is None


@pytest.mark.asyncio
async def test_post_test_connection_validation():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/providers/test",
            json={"vendor_id": "custom", "api_key": "sk-test"},
        )
    assert r.status_code == 400
