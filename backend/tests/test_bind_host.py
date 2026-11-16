"""本地监听地址默认只绑回环。"""

from __future__ import annotations

from app.config import Settings
from app.main import local_uvicorn_options


def test_local_uvicorn_binds_loopback_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("BIND_HOST", raising=False)
    settings = Settings(_env_file=None, data_dir=tmp_path)
    options = local_uvicorn_options(settings)
    assert options["host"] == "127.0.0.1"
    assert options["port"] == 8000
    assert options["reload"] is True


def test_bind_host_override_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setenv("BIND_HOST", "0.0.0.0")
    settings = Settings(_env_file=None, data_dir=tmp_path)
    assert local_uvicorn_options(settings)["host"] == "0.0.0.0"
