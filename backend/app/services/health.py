"""接口、数据库与当前生效模型的健康检查。

探测复用厂商连接测试，用已启用的配置或 .env 里的续写密钥，响应里不回传密钥。
"""

from __future__ import annotations

from sqlalchemy import func, select, text

from app import db as db_mod
from app.config import get_settings
from app.models import Novel
from app.schemas.health import CheckOut, HealthChecks, HealthOut, LlmCheckOut, LlmStageOut
from app.services.llm_profiles import effective_llm
from app.services.providers import test_connection

_PUBLIC_KEYS = {"anonymous", "none", "no-key", "nokey"}


def key_configured(api_key: str | None) -> bool:
    """占位 sk-your-* 视为未配置；anonymous/none 等免费匿名档视为已配置。"""
    key = (api_key or "").strip()
    if not key or key.startswith("sk-your"):
        return False
    return True


def _short(exc: Exception) -> str:
    msg = str(exc).strip() or exc.__class__.__name__
    return msg[:200]


def _scrub(text_value: str, secret: str) -> str:
    key = (secret or "").strip()
    if not text_value or not key or key.lower() in _PUBLIC_KEYS:
        return text_value
    return text_value.replace(key, "***")


def _stages(settings) -> list[LlmStageOut]:
    return [
        LlmStageOut(
            stage="summary",
            label="摘要 / 抽取",
            configured=key_configured(settings.summary_api_key),
            provider=settings.summary_provider,
            model=settings.summary_model,
            base_url=settings.summary_base_url,
        ),
        LlmStageOut(
            stage="generation",
            label="大纲 / 续写",
            configured=key_configured(settings.generation_api_key),
            provider=settings.generation_provider,
            model=settings.generation_model,
            base_url=settings.generation_base_url,
        ),
        LlmStageOut(
            stage="embedding",
            label="向量化",
            configured=key_configured(settings.embedding_api_key),
            provider="openai",
            model=settings.embedding_model,
            base_url=settings.embedding_base_url,
        ),
    ]


async def _db_snapshot() -> tuple[bool, str, int]:
    factory = db_mod.SessionLocal
    if factory is None:
        return False, "数据库未初始化", 0
    try:
        async with factory() as session:
            await session.execute(text("SELECT 1"))
            count = await session.scalar(select(func.count()).select_from(Novel))
        return True, "可读写", int(count or 0)
    except Exception as exc:  # noqa: BLE001 — 健康检查要把失败说清楚
        return False, _short(exc), 0


def _idle_detail(eff) -> str:
    if eff.source == "profile" and eff.profile_name:
        return f"正在用配置「{eff.profile_name}」，尚未探测"
    return "续写密钥已配置，尚未探测"


async def _llm_check(*, probe: bool) -> LlmCheckOut:
    eff = effective_llm()
    stages = _stages(eff)
    secret = eff.generation_api_key or ""
    configured = key_configured(secret)
    if not configured:
        return LlmCheckOut(
            ok=False,
            configured=False,
            probed=False,
            detail="续写密钥还没配置",
            stages=stages,
        )
    if not probe:
        return LlmCheckOut(
            ok=True,
            configured=True,
            probed=False,
            detail=_idle_detail(eff),
            stages=stages,
        )

    base_url = (eff.generation_base_url or "").strip()
    model = (eff.generation_model or "").strip()
    if not base_url or not model:
        return LlmCheckOut(
            ok=False,
            configured=True,
            probed=False,
            detail="续写地址或模型名为空",
            stages=stages,
        )

    result = await test_connection(api_key=secret, base_url=base_url, model=model)
    error = _scrub(result.get("error") or "", secret)
    reply = _scrub(result.get("reply") or "", secret) or None
    if result.get("ok"):
        detail = "续写模型有响应"
        ok = True
    else:
        detail = error or "探测失败"
        ok = False
    return LlmCheckOut(
        ok=ok,
        configured=True,
        probed=True,
        detail=detail[:500],
        latency_ms=result.get("latency_ms"),
        reply=reply,
        stages=stages,
    )


async def collect_health(*, probe_llm: bool = False) -> HealthOut:
    settings = get_settings()
    db_ok, db_detail, novel_count = await _db_snapshot()
    llm = await _llm_check(probe=probe_llm)
    return HealthOut(
        status="ok" if db_ok else "degraded",
        app=settings.app_name,
        ready=db_ok and llm.ok,
        first_run=novel_count == 0 or not llm.configured,
        novel_count=novel_count,
        checks=HealthChecks(
            api=CheckOut(ok=True, detail="可访问"),
            db=CheckOut(ok=db_ok, detail=db_detail),
            llm=llm,
        ),
    )
