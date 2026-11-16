"""LLM 厂商预设与命名配置 API。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.services.llm_profiles import (
    ProfileNameTaken,
    ProfileNotFound,
    ProfileValidationError,
    activate_profile,
    active_public,
    create_profile,
    delete_profile,
    list_profile_rows,
    profile_public,
    update_profile,
    update_profile_from_current,
)
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


class KeyStatusOut(BaseModel):
    mode: Literal["anonymous", "keyed"]
    mask: str | None = None


class ProfileOut(BaseModel):
    id: int
    name: str
    vendor_id: str | None = None
    is_active: bool
    summary_follows_generation: bool
    generation_provider: str
    generation_base_url: str
    generation_model: str
    generation_key: KeyStatusOut
    summary_provider: str
    summary_base_url: str
    summary_model: str
    summary_key: KeyStatusOut
    embedding_base_url: str
    embedding_model: str
    embedding_dims: int
    embedding_key: KeyStatusOut
    created_at: datetime
    updated_at: datetime


class ProfileListOut(BaseModel):
    profiles: list[ProfileOut]


class ActiveLLMOut(BaseModel):
    source: Literal["env", "profile"]
    profile_id: int | None = None
    profile_name: str | None = None
    vendor_id: str | None = None
    summary_follows_generation: bool
    generation_provider: str
    generation_base_url: str
    generation_model: str
    generation_key: KeyStatusOut
    summary_provider: str
    summary_base_url: str
    summary_model: str
    summary_key: KeyStatusOut
    embedding_base_url: str
    embedding_model: str
    embedding_dims: int
    embedding_key: KeyStatusOut
    vec_dims: int
    dims_mismatch: bool


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    from_current: bool = False
    activate: bool = False
    vendor_id: str | None = None
    summary_follows_generation: bool = True
    generation_provider: Literal["openai", "anthropic"] = "openai"
    generation_base_url: str = ""
    generation_api_key: str = ""
    generation_model: str = ""
    summary_provider: Literal["openai", "anthropic"] | None = None
    summary_base_url: str | None = None
    summary_api_key: str | None = None
    summary_model: str | None = None
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""
    embedding_dims: int | None = None


class ProfileUpdate(BaseModel):
    name: str | None = None
    vendor_id: str | None = None
    summary_follows_generation: bool | None = None
    generation_provider: Literal["openai", "anthropic"] | None = None
    generation_base_url: str | None = None
    generation_api_key: str | None = None
    generation_model: str | None = None
    summary_provider: Literal["openai", "anthropic"] | None = None
    summary_base_url: str | None = None
    summary_api_key: str | None = None
    summary_model: str | None = None
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    embedding_model: str | None = None
    embedding_dims: int | None = None


def _profile_http(exc: Exception) -> HTTPException:
    if isinstance(exc, ProfileNotFound):
        return HTTPException(status_code=404, detail="配置不存在")
    if isinstance(exc, ProfileNameTaken):
        return HTTPException(status_code=409, detail="已有同名配置")
    if isinstance(exc, ProfileValidationError):
        return HTTPException(status_code=400, detail=str(exc))
    raise exc


@router.get("/active", response_model=ActiveLLMOut)
async def get_active_settings() -> ActiveLLMOut:
    return ActiveLLMOut(**active_public())


@router.get("/profiles", response_model=ProfileListOut)
async def get_profiles(session: AsyncSession = Depends(get_session)) -> ProfileListOut:
    rows = await list_profile_rows(session)
    return ProfileListOut(profiles=[ProfileOut(**profile_public(row)) for row in rows])


@router.post("/profiles", response_model=ProfileOut)
async def post_profile(
    body: ProfileCreate,
    session: AsyncSession = Depends(get_session),
) -> ProfileOut:
    try:
        row = await create_profile(
            session,
            name=body.name,
            from_current=body.from_current,
            activate=body.activate,
            payload=None if body.from_current else body.model_dump(),
        )
    except (ProfileNotFound, ProfileNameTaken, ProfileValidationError) as exc:
        raise _profile_http(exc) from exc
    return ProfileOut(**profile_public(row))


@router.patch("/profiles/{profile_id}", response_model=ProfileOut)
async def patch_profile(
    profile_id: int,
    body: ProfileUpdate,
    session: AsyncSession = Depends(get_session),
) -> ProfileOut:
    try:
        row = await update_profile(session, profile_id, body.model_dump(exclude_unset=True))
    except (ProfileNotFound, ProfileNameTaken, ProfileValidationError) as exc:
        raise _profile_http(exc) from exc
    return ProfileOut(**profile_public(row))


@router.post("/profiles/{profile_id}/activate", response_model=ProfileOut)
async def post_activate_profile(
    profile_id: int,
    session: AsyncSession = Depends(get_session),
) -> ProfileOut:
    try:
        row = await activate_profile(session, profile_id)
    except (ProfileNotFound, ProfileNameTaken, ProfileValidationError) as exc:
        raise _profile_http(exc) from exc
    return ProfileOut(**profile_public(row))


@router.post("/profiles/{profile_id}/update-from-current", response_model=ProfileOut)
async def post_update_from_current(
    profile_id: int,
    session: AsyncSession = Depends(get_session),
) -> ProfileOut:
    try:
        row = await update_profile_from_current(session, profile_id)
    except (ProfileNotFound, ProfileNameTaken, ProfileValidationError) as exc:
        raise _profile_http(exc) from exc
    return ProfileOut(**profile_public(row))


@router.delete("/profiles/{profile_id}")
async def remove_profile(
    profile_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    try:
        await delete_profile(session, profile_id)
    except (ProfileNotFound, ProfileNameTaken, ProfileValidationError) as exc:
        raise _profile_http(exc) from exc
    return {"message": "已删除"}
