"""LLM 厂商预设 API。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.providers import list_presets, resolve_connection, test_connection

router = APIRouter(prefix="/api/providers", tags=["providers"])


class ConnectionTestRequest(BaseModel):
    vendor_id: str | None = Field(default=None, description="预设 id，如 openai / deepseek")
    api_key: str = Field(..., min_length=1, description="API Key，仅用于本次探测，不落库")
    base_url: str | None = Field(default=None, description="覆盖预设 Base URL")
    model: str | None = Field(default=None, description="覆盖预设默认模型")


class ConnectionTestResponse(BaseModel):
    ok: bool
    error: str | None = None
    latency_ms: int | None = None
    reply: str | None = None
    base_url: str | None = None
    model: str | None = None


@router.get("")
async def get_presets() -> dict[str, Any]:
    return {"presets": list_presets()}


@router.post("/test", response_model=ConnectionTestResponse)
async def post_test_connection(body: ConnectionTestRequest) -> ConnectionTestResponse:
    try:
        base_url, model = resolve_connection(
            vendor_id=body.vendor_id,
            base_url=body.base_url,
            model=body.model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = await test_connection(api_key=body.api_key, base_url=base_url, model=model)
    return ConnectionTestResponse(
        ok=result["ok"],
        error=result["error"],
        latency_ms=result["latency_ms"],
        reply=result["reply"],
        base_url=base_url,
        model=model,
    )
