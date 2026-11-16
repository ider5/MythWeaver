"""健康检查响应。不包含任何密钥。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class CheckOut(BaseModel):
    ok: bool
    detail: str


class LlmStageOut(BaseModel):
    stage: str
    label: str
    configured: bool
    provider: str
    model: str
    base_url: str


class LlmCheckOut(BaseModel):
    ok: bool
    configured: bool
    probed: bool
    detail: str
    latency_ms: int | None = None
    reply: str | None = None
    stages: list[LlmStageOut]


class HealthChecks(BaseModel):
    api: CheckOut
    db: CheckOut
    llm: LlmCheckOut


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    app: str
    ready: bool
    first_run: bool
    novel_count: int
    checks: HealthChecks
