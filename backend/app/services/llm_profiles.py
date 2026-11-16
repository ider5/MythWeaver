"""命名 LLM 配置：存本机 SQLite，启用后覆盖进程内的生效端点。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import LLMProfile
from app.services.providers import get_preset, list_presets

_ANONYMOUS = {"", "anonymous", "none", "no-key", "nokey"}
_active: EffectiveLLM | None = None


class ProfileNotFound(Exception):
    pass


class ProfileNameTaken(Exception):
    pass


class ProfileValidationError(Exception):
    pass


@dataclass(frozen=True)
class EffectiveLLM:
    source: str
    profile_id: int | None
    profile_name: str | None
    vendor_id: str | None
    summary_follows_generation: bool
    summary_provider: str
    summary_base_url: str
    summary_api_key: str
    summary_model: str
    generation_provider: str
    generation_base_url: str
    generation_api_key: str
    generation_model: str
    embedding_base_url: str
    embedding_api_key: str
    embedding_model: str
    embedding_dims: int

    def __repr__(self) -> str:
        return (
            f"EffectiveLLM(source={self.source!r}, profile={self.profile_name!r}, "
            f"generation_model={self.generation_model!r}, embedding_model={self.embedding_model!r})"
        )


def reset_llm_profile_state() -> None:
    global _active
    _active = None


def effective_llm() -> EffectiveLLM:
    if _active is not None:
        return _active
    return _from_settings(get_settings())


def key_view(secret: str | None) -> dict[str, str | None]:
    """匿名 / 占位密钥不回掩码；真实密钥只留末四位。"""
    raw = (secret or "").strip()
    if raw.lower() in _ANONYMOUS or raw.startswith("sk-your"):
        return {"mode": "anonymous", "mask": None}
    mask = "••••" if len(raw) <= 8 else f"••••{raw[-4:]}"
    return {"mode": "keyed", "mask": mask}


def profile_public(row: LLMProfile) -> dict[str, Any]:
    follows = bool(row.summary_follows_generation)
    summary_provider = row.generation_provider if follows else row.summary_provider
    summary_base_url = row.generation_base_url if follows else row.summary_base_url
    summary_model = row.generation_model if follows else row.summary_model
    summary_key = row.generation_api_key if follows else row.summary_api_key
    return {
        "id": row.id,
        "name": row.name,
        "vendor_id": row.vendor_id,
        "is_active": bool(row.is_active),
        "summary_follows_generation": follows,
        "generation_provider": row.generation_provider,
        "generation_base_url": row.generation_base_url,
        "generation_model": row.generation_model,
        "generation_key": key_view(row.generation_api_key),
        "summary_provider": summary_provider,
        "summary_base_url": summary_base_url,
        "summary_model": summary_model,
        "summary_key": key_view(summary_key),
        "embedding_base_url": row.embedding_base_url,
        "embedding_model": row.embedding_model,
        "embedding_dims": row.embedding_dims,
        "embedding_key": key_view(row.embedding_api_key),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def active_public() -> dict[str, Any]:
    eff = effective_llm()
    vec_dims = int(get_settings().embedding_dims)
    return {
        "source": eff.source,
        "profile_id": eff.profile_id,
        "profile_name": eff.profile_name,
        "vendor_id": eff.vendor_id,
        "summary_follows_generation": eff.summary_follows_generation,
        "generation_provider": eff.generation_provider,
        "generation_base_url": eff.generation_base_url,
        "generation_model": eff.generation_model,
        "generation_key": key_view(eff.generation_api_key),
        "summary_provider": eff.summary_provider,
        "summary_base_url": eff.summary_base_url,
        "summary_model": eff.summary_model,
        "summary_key": key_view(eff.summary_api_key),
        "embedding_base_url": eff.embedding_base_url,
        "embedding_model": eff.embedding_model,
        "embedding_dims": eff.embedding_dims,
        "embedding_key": key_view(eff.embedding_api_key),
        "vec_dims": vec_dims,
        "dims_mismatch": eff.embedding_dims != vec_dims,
    }


async def list_profile_rows(session: AsyncSession) -> list[LLMProfile]:
    rows = (await session.execute(select(LLMProfile).order_by(LLMProfile.id.asc()))).scalars().all()
    return list(rows)


async def reload_active_profile(session: AsyncSession) -> None:
    rows = (
        await session.execute(
            select(LLMProfile).where(LLMProfile.is_active.is_(True)).order_by(LLMProfile.id.asc())
        )
    ).scalars().all()
    if not rows:
        reset_llm_profile_state()
        return
    primary = rows[0]
    if len(rows) > 1:
        for extra in rows[1:]:
            extra.is_active = False
        await session.commit()
    _install(primary)


async def create_profile(
    session: AsyncSession,
    *,
    name: str,
    from_current: bool,
    activate: bool,
    payload: dict[str, Any] | None,
) -> LLMProfile:
    cleaned = _clean_name(name)
    await _ensure_name(session, cleaned)
    now = _now()
    if from_current:
        eff = effective_llm()
        row = LLMProfile(
            name=cleaned,
            vendor_id=eff.vendor_id,
            summary_follows_generation=eff.summary_follows_generation,
            generation_provider=eff.generation_provider,
            generation_base_url=eff.generation_base_url,
            generation_api_key=eff.generation_api_key,
            generation_model=eff.generation_model,
            summary_provider=eff.summary_provider,
            summary_base_url=eff.summary_base_url,
            summary_api_key=eff.summary_api_key,
            summary_model=eff.summary_model,
            embedding_base_url=eff.embedding_base_url,
            embedding_api_key=eff.embedding_api_key,
            embedding_model=eff.embedding_model,
            embedding_dims=eff.embedding_dims,
            is_active=False,
            created_at=now,
            updated_at=now,
        )
    else:
        draft = _draft_from_payload(payload or {})
        row = LLMProfile(
            name=cleaned,
            is_active=False,
            created_at=now,
            updated_at=now,
            **draft,
        )
    if activate:
        await _clear_active(session)
        row.is_active = True
    session.add(row)
    await _commit_name(session, cleaned)
    await session.refresh(row)
    if row.is_active:
        _install(row)
    return row


async def update_profile(session: AsyncSession, profile_id: int, data: dict[str, Any]) -> LLMProfile:
    row = await _get(session, profile_id)
    if "name" in data and data["name"] is not None:
        cleaned = _clean_name(data["name"])
        await _ensure_name(session, cleaned, exclude_id=row.id)
        row.name = cleaned
    if "vendor_id" in data:
        row.vendor_id = _clean_vendor(data["vendor_id"])
    if data.get("generation_provider"):
        row.generation_provider = _clean_provider(data["generation_provider"])
    if data.get("generation_base_url"):
        row.generation_base_url = _clean_url(data["generation_base_url"], field="续写 Base URL")
    if data.get("generation_model"):
        row.generation_model = _clean_model(data["generation_model"], field="续写模型")
    if "generation_api_key" in data:
        row.generation_api_key = (data.get("generation_api_key") or "").strip()
    if "summary_follows_generation" in data and data["summary_follows_generation"] is not None:
        row.summary_follows_generation = bool(data["summary_follows_generation"])
    if data.get("summary_provider"):
        row.summary_provider = _clean_provider(data["summary_provider"])
    if data.get("summary_base_url"):
        row.summary_base_url = _clean_url(data["summary_base_url"], field="摘要 Base URL")
    if data.get("summary_model"):
        row.summary_model = _clean_model(data["summary_model"], field="摘要模型")
    if "summary_api_key" in data:
        row.summary_api_key = (data.get("summary_api_key") or "").strip()
    if data.get("embedding_base_url"):
        row.embedding_base_url = _clean_url(data["embedding_base_url"], field="向量 Base URL")
    if data.get("embedding_model"):
        row.embedding_model = _clean_model(data["embedding_model"], field="向量模型")
    if "embedding_api_key" in data:
        row.embedding_api_key = (data.get("embedding_api_key") or "").strip()
    if data.get("embedding_dims") is not None:
        row.embedding_dims = _clean_dims(data["embedding_dims"])
    _sync_summary(row)
    row.updated_at = _now()
    await _commit_name(session, row.name)
    await session.refresh(row)
    if row.is_active:
        _install(row)
    return row


async def update_profile_from_current(session: AsyncSession, profile_id: int) -> LLMProfile:
    row = await _get(session, profile_id)
    eff = effective_llm()
    row.vendor_id = eff.vendor_id
    row.summary_follows_generation = eff.summary_follows_generation
    row.generation_provider = eff.generation_provider
    row.generation_base_url = eff.generation_base_url
    row.generation_api_key = eff.generation_api_key
    row.generation_model = eff.generation_model
    row.summary_provider = eff.summary_provider
    row.summary_base_url = eff.summary_base_url
    row.summary_api_key = eff.summary_api_key
    row.summary_model = eff.summary_model
    row.embedding_base_url = eff.embedding_base_url
    row.embedding_api_key = eff.embedding_api_key
    row.embedding_model = eff.embedding_model
    row.embedding_dims = eff.embedding_dims
    row.updated_at = _now()
    await session.commit()
    await session.refresh(row)
    if row.is_active:
        _install(row)
    return row


async def activate_profile(session: AsyncSession, profile_id: int) -> LLMProfile:
    row = await _get(session, profile_id)
    await _clear_active(session)
    row.is_active = True
    row.updated_at = _now()
    await session.commit()
    await session.refresh(row)
    _install(row)
    return row


async def delete_profile(session: AsyncSession, profile_id: int) -> None:
    row = await _get(session, profile_id)
    was_active = bool(row.is_active)
    await session.delete(row)
    await session.commit()
    if was_active:
        reset_llm_profile_state()


def _install(row: LLMProfile) -> None:
    global _active
    _active = _from_row(row)


def _from_settings(settings) -> EffectiveLLM:  # noqa: ANN001
    gen_url = (settings.generation_base_url or "").rstrip("/")
    sum_url = (settings.summary_base_url or "").rstrip("/")
    same = (
        settings.summary_provider == settings.generation_provider
        and sum_url == gen_url
        and settings.summary_model == settings.generation_model
        and (settings.summary_api_key or "") == (settings.generation_api_key or "")
    )
    return EffectiveLLM(
        source="env",
        profile_id=None,
        profile_name=None,
        vendor_id=infer_vendor_id(gen_url),
        summary_follows_generation=same,
        summary_provider=settings.summary_provider,
        summary_base_url=sum_url,
        summary_api_key=settings.summary_api_key or "",
        summary_model=settings.summary_model,
        generation_provider=settings.generation_provider,
        generation_base_url=gen_url,
        generation_api_key=settings.generation_api_key or "",
        generation_model=settings.generation_model,
        embedding_base_url=(settings.embedding_base_url or "").rstrip("/"),
        embedding_api_key=settings.embedding_api_key or "",
        embedding_model=settings.embedding_model,
        embedding_dims=int(settings.embedding_dims),
    )


def _from_row(row: LLMProfile) -> EffectiveLLM:
    follows = bool(row.summary_follows_generation)
    return EffectiveLLM(
        source="profile",
        profile_id=row.id,
        profile_name=row.name,
        vendor_id=row.vendor_id or infer_vendor_id(row.generation_base_url),
        summary_follows_generation=follows,
        summary_provider=row.generation_provider if follows else row.summary_provider,
        summary_base_url=row.generation_base_url if follows else row.summary_base_url,
        summary_api_key=row.generation_api_key if follows else row.summary_api_key,
        summary_model=row.generation_model if follows else row.summary_model,
        generation_provider=row.generation_provider,
        generation_base_url=row.generation_base_url,
        generation_api_key=row.generation_api_key,
        generation_model=row.generation_model,
        embedding_base_url=row.embedding_base_url,
        embedding_api_key=row.embedding_api_key,
        embedding_model=row.embedding_model,
        embedding_dims=int(row.embedding_dims),
    )


def infer_vendor_id(base_url: str | None) -> str | None:
    url = (base_url or "").rstrip("/")
    if not url:
        return None
    for preset in list_presets():
        preset_url = (preset.get("base_url") or "").rstrip("/")
        if preset_url and preset_url == url:
            return str(preset["id"])
    return None


def _draft_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    follows = bool(payload.get("summary_follows_generation", True))
    generation_provider = _clean_provider(payload.get("generation_provider") or "openai")
    generation_base_url = _clean_url(payload.get("generation_base_url") or "", field="续写 Base URL")
    generation_model = _clean_model(payload.get("generation_model") or "", field="续写模型")
    generation_api_key = (payload.get("generation_api_key") or "").strip()
    if follows:
        summary_provider = generation_provider
        summary_base_url = generation_base_url
        summary_model = generation_model
        summary_api_key = generation_api_key
    else:
        summary_provider = _clean_provider(payload.get("summary_provider") or generation_provider)
        summary_base_url = _clean_url(payload.get("summary_base_url") or "", field="摘要 Base URL")
        summary_model = _clean_model(payload.get("summary_model") or "", field="摘要模型")
        summary_api_key = (payload.get("summary_api_key") or "").strip()
    return {
        "vendor_id": _clean_vendor(payload.get("vendor_id")),
        "summary_follows_generation": follows,
        "generation_provider": generation_provider,
        "generation_base_url": generation_base_url,
        "generation_api_key": generation_api_key,
        "generation_model": generation_model,
        "summary_provider": summary_provider,
        "summary_base_url": summary_base_url,
        "summary_api_key": summary_api_key,
        "summary_model": summary_model,
        "embedding_base_url": _clean_url(payload.get("embedding_base_url") or "", field="向量 Base URL"),
        "embedding_api_key": (payload.get("embedding_api_key") or "").strip(),
        "embedding_model": _clean_model(payload.get("embedding_model") or "", field="向量模型"),
        "embedding_dims": _clean_dims(payload.get("embedding_dims")),
    }


def _sync_summary(row: LLMProfile) -> None:
    if not row.summary_follows_generation:
        return
    row.summary_provider = row.generation_provider
    row.summary_base_url = row.generation_base_url
    row.summary_api_key = row.generation_api_key
    row.summary_model = row.generation_model


async def _get(session: AsyncSession, profile_id: int) -> LLMProfile:
    row = await session.get(LLMProfile, profile_id)
    if row is None:
        raise ProfileNotFound()
    return row


async def _ensure_name(session: AsyncSession, name: str, exclude_id: int | None = None) -> None:
    rows = (await session.execute(select(LLMProfile.id, LLMProfile.name))).all()
    folded = name.casefold()
    for existing_id, existing_name in rows:
        if exclude_id is not None and existing_id == exclude_id:
            continue
        if (existing_name or "").casefold() == folded:
            raise ProfileNameTaken()


async def _clear_active(session: AsyncSession) -> None:
    rows = (await session.execute(select(LLMProfile).where(LLMProfile.is_active.is_(True)))).scalars().all()
    for row in rows:
        row.is_active = False


async def _commit_name(session: AsyncSession, name: str) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ProfileNameTaken() from exc


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _clean_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not cleaned:
        raise ProfileValidationError("配置名称不能为空")
    if len(cleaned) > 64:
        raise ProfileValidationError("配置名称最多 64 字")
    if any(ch in cleaned for ch in "\n\r\t"):
        raise ProfileValidationError("配置名称不能换行")
    return cleaned


def _clean_provider(value: str) -> str:
    if value not in ("openai", "anthropic"):
        raise ProfileValidationError("协议只能是 openai 或 anthropic")
    return value


def _clean_url(url: str, *, field: str) -> str:
    cleaned = (url or "").strip().rstrip("/")
    if not cleaned.startswith(("http://", "https://")):
        raise ProfileValidationError(f"{field} 需以 http:// 或 https:// 开头")
    return cleaned


def _clean_model(model: str, *, field: str) -> str:
    cleaned = (model or "").strip()
    if not cleaned:
        raise ProfileValidationError(f"缺少{field}")
    if len(cleaned) > 128:
        raise ProfileValidationError(f"{field}过长")
    return cleaned


def _clean_dims(value: int | None) -> int:
    if value is None:
        return int(get_settings().embedding_dims)
    try:
        dims = int(value)
    except (TypeError, ValueError) as exc:
        raise ProfileValidationError("向量维度无效") from exc
    if dims < 1 or dims > 8192:
        raise ProfileValidationError("向量维度需在 1 到 8192 之间")
    return dims


def _clean_vendor(vendor_id: str | None) -> str | None:
    if vendor_id is None:
        return None
    cleaned = vendor_id.strip()
    if not cleaned:
        return None
    if get_preset(cleaned) is None:
        raise ProfileValidationError("未知厂商预设")
    return cleaned
