"""LLM 厂商预设与连接测试。"""

from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI

# 官方 OpenAI 兼容端点；密钥从不持久化到此模块。
VENDOR_PRESETS: list[dict[str, Any]] = [
    {
        "id": "openai",
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "models": ["gpt-4o", "gpt-4o-mini", "o4-mini"],
        "docs_url": "https://platform.openai.com/docs",
        "notes": "官方 OpenAI API。",
    },
    {
        "id": "deepseek",
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "docs_url": "https://api-docs.deepseek.com/",
        "notes": "OpenAI 兼容；适合中文长文。",
    },
    {
        "id": "moonshot",
        "label": "Moonshot / Kimi",
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-128k",
        "models": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
        "docs_url": "https://platform.moonshot.cn/docs",
        "notes": "长上下文；OpenAI 兼容。",
    },
    {
        "id": "qwen",
        "label": "通义千问 (DashScope)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
        "models": ["qwen-turbo", "qwen-plus", "qwen-max", "qwen-long"],
        "docs_url": "https://help.aliyun.com/zh/model-studio/",
        "notes": "阿里云百炼兼容模式。",
    },
    {
        "id": "zhipu",
        "label": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4-flash",
        "models": ["glm-4-flash", "glm-4-air", "glm-4-plus"],
        "docs_url": "https://open.bigmodel.cn/dev/api",
        "notes": "智谱 OpenAI 兼容端点。",
    },
    {
        "id": "openrouter",
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "openai/gpt-4o-mini",
        "models": ["openai/gpt-4o-mini", "deepseek/deepseek-chat", "anthropic/claude-3.5-sonnet"],
        "docs_url": "https://openrouter.ai/docs",
        "notes": "多模型路由；需自备 Key。",
    },
    {
        "id": "ollama",
        "label": "Ollama (本地)",
        "base_url": "http://127.0.0.1:11434/v1",
        "default_model": "llama3.2",
        "models": ["llama3.2", "qwen2.5", "mistral"],
        "docs_url": "https://ollama.com/",
        "notes": "本地 OpenAI 兼容；Key 可填 ollama。",
    },
    {
        "id": "ovh",
        "label": "OVH AI Endpoints (免费匿名)",
        "base_url": "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1",
        "default_model": "Mistral-Small-3.2-24B-Instruct-2506",
        "models": [
            "Mistral-Small-3.2-24B-Instruct-2506",
            "Meta-Llama-3_3-70B-Instruct",
            "Qwen3.5-9B",
            "gpt-oss-20b",
        ],
        "docs_url": "https://endpoints.ai.cloud.ovh.net/",
        "notes": "匿名免费档（限速）；Key 填 anonymous，勿传真实 Bearer。向量可用 bge-m3。",
    },
    {
        "id": "custom",
        "label": "自定义 OpenAI 兼容",
        "base_url": "",
        "default_model": "",
        "models": [],
        "docs_url": "",
        "notes": "自行填写 Base URL 与模型名。",
    },
]

_PRESET_BY_ID = {p["id"]: p for p in VENDOR_PRESETS}


def list_presets() -> list[dict[str, Any]]:
    return [dict(p) for p in VENDOR_PRESETS]


def get_preset(vendor_id: str) -> dict[str, Any] | None:
    p = _PRESET_BY_ID.get(vendor_id)
    return dict(p) if p else None


def resolve_connection(
    *,
    vendor_id: str | None,
    base_url: str | None,
    model: str | None,
) -> tuple[str, str]:
    """合并预设与覆盖项，返回 (base_url, model)。"""
    preset = get_preset(vendor_id) if vendor_id else None
    resolved_url = (base_url or "").strip() or (preset["base_url"] if preset else "")
    resolved_model = (model or "").strip() or (preset["default_model"] if preset else "")
    if not resolved_url:
        raise ValueError("缺少 base_url：请选择厂商预设或手动填写")
    if not resolved_model:
        raise ValueError("缺少 model：请选择厂商预设或手动填写")
    return resolved_url.rstrip("/"), resolved_model


async def test_connection(
    *,
    api_key: str,
    base_url: str,
    model: str,
) -> dict[str, Any]:
    """对 OpenAI 兼容端点发起最小 chat 探测；不持久化密钥。"""
    import time

    import httpx

    key = (api_key or "").strip()
    if not key:
        return {"ok": False, "error": "api_key 不能为空", "latency_ms": None, "reply": None}

    anon = key.lower() in ("anonymous", "none", "no-key", "nokey")
    if anon:

        class _StripAuth(httpx.Auth):
            def auth_flow(self, request: httpx.Request):
                request.headers.pop("Authorization", None)
                yield request

        client = AsyncOpenAI(
            api_key="anonymous",
            base_url=base_url.rstrip("/"),
            timeout=30.0,
            http_client=httpx.AsyncClient(auth=_StripAuth(), timeout=30.0),
        )
    else:
        client = AsyncOpenAI(api_key=key, base_url=base_url.rstrip("/"), timeout=30.0)

    t0 = time.perf_counter()
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with exactly: ok"}],
            max_tokens=8,
            temperature=0,
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)
        reply = (resp.choices[0].message.content or "").strip() if resp.choices else ""
        return {"ok": True, "error": None, "latency_ms": latency_ms, "reply": reply[:200]}
    except Exception as exc:  # noqa: BLE001 — 表面给前端可读错误
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return {"ok": False, "error": str(exc)[:500], "latency_ms": latency_ms, "reply": None}
    finally:
        await client.close()
