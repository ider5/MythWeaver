"""双协议统一 LLM 客户端：openai | anthropic，统一 chat/stream/embed。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal, Optional

from app.config import Provider, get_settings
from app.llm.rate_limiter import (
    get_embedding_concurrency_gate,
    get_llm_concurrency_gate,
    get_rate_limiter,
    with_retry,
)
from app.utils.chinese_text import count_tokens

Role = Literal["system", "user", "assistant"]


@dataclass
class ChatMessage:
    role: Role
    content: str


@dataclass
class ChatResult:
    text: str
    input_tokens: int
    output_tokens: int
    provider: str
    model: str


@dataclass
class ModelEndpoint:
    provider: Provider
    base_url: str
    api_key: str
    model: str


class LLMClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.limiter = get_rate_limiter()

    def summary_endpoint(self) -> ModelEndpoint:
        s = self.settings
        return ModelEndpoint(s.summary_provider, s.summary_base_url, s.summary_api_key, s.summary_model)

    def generation_endpoint(self) -> ModelEndpoint:
        s = self.settings
        return ModelEndpoint(
            s.generation_provider, s.generation_base_url, s.generation_api_key, s.generation_model
        )

    async def chat(
        self,
        messages: list[ChatMessage] | list[dict[str, str]],
        *,
        endpoint: ModelEndpoint | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        purpose: str = "chat",
    ) -> ChatResult:
        ep = endpoint or self.summary_endpoint()
        msgs = self._normalize(messages)
        est = sum(count_tokens(m["content"]) for m in msgs) + max_tokens
        await self.limiter.acquire(est)

        async def _call() -> ChatResult:
            if ep.provider == "anthropic":
                return await self._anthropic_chat(ep, msgs, temperature, max_tokens)
            return await self._openai_chat(ep, msgs, temperature, max_tokens)

        # 持闸贯穿重试，避免退避期间其它请求继续打满组织并发
        async with get_llm_concurrency_gate():
            return await with_retry(_call)

    async def stream(
        self,
        messages: list[ChatMessage] | list[dict[str, str]],
        *,
        endpoint: ModelEndpoint | None = None,
        temperature: float = 0.8,
        max_tokens: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """流式增量统一为 {delta_text}，结束时 yield {done, text, input_tokens, output_tokens}。"""
        ep = endpoint or self.generation_endpoint()
        msgs = self._normalize(messages)
        mt = max_tokens if max_tokens is not None else self.settings.generation_max_tokens
        est = sum(count_tokens(m["content"]) for m in msgs) + mt
        await self.limiter.acquire(est)

        async with get_llm_concurrency_gate():
            if ep.provider == "anthropic":
                async for chunk in self._anthropic_stream(ep, msgs, temperature, mt):
                    yield chunk
            else:
                async for chunk in self._openai_stream(ep, msgs, temperature, mt):
                    yield chunk

    async def embed(self, texts: list[str]) -> tuple[list[list[float]], int]:
        """返回 (vectors, input_tokens)。"""
        s = self.settings
        if not texts:
            return [], 0
        est = sum(count_tokens(t) for t in texts)
        await self.limiter.acquire(est)

        async def _call() -> tuple[list[list[float]], int]:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=s.embedding_api_key or "sk-placeholder", base_url=s.embedding_base_url)
            # 智谱 Embedding-3 等支持 dimensions；与 EMBEDDING_DIMS 对齐（默认 2048）
            create_kwargs: dict[str, Any] = {"model": s.embedding_model, "input": texts}
            if s.embedding_dims:
                create_kwargs["dimensions"] = s.embedding_dims
            resp = await client.embeddings.create(**create_kwargs)
            # 按 input index 对齐，避免部分厂商乱序返回
            ordered: list[list[float] | None] = [None] * len(texts)
            for item in resp.data:
                idx = getattr(item, "index", None)
                if idx is None:
                    # 无 index 时按返回顺序填剩余空位
                    for i, slot in enumerate(ordered):
                        if slot is None:
                            ordered[i] = list(item.embedding)
                            break
                else:
                    ordered[int(idx)] = list(item.embedding)
            if any(v is None for v in ordered):
                # 兜底：直接按 data 顺序
                ordered = [list(item.embedding) for item in resp.data]
            vectors = [v for v in ordered if v is not None]
            tokens = getattr(resp.usage, "total_tokens", est) if resp.usage else est
            return vectors, int(tokens)

        async with get_embedding_concurrency_gate():
            return await with_retry(_call)

    def _normalize(self, messages: list[ChatMessage] | list[dict[str, str]]) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for m in messages:
            if isinstance(m, ChatMessage):
                out.append({"role": m.role, "content": m.content})
            else:
                out.append({"role": m["role"], "content": m["content"]})
        return out

    @staticmethod
    def _is_kimi_endpoint(ep: ModelEndpoint) -> bool:
        """Moonshot/Kimi：官方要求勿传 temperature/top_p 等采样参数。"""
        model = (ep.model or "").lower()
        base = (ep.base_url or "").lower()
        return (
            model.startswith("kimi-")
            or model.startswith("moonshot-")
            or "moonshot." in base
            or "kimi.ai" in base
        )

    def _http_timeout(self):
        """连接短超时；读超时按 chunk 续命，避免无 timeout 永久挂死或默认过短半截断。"""
        import httpx

        s = self.settings
        return httpx.Timeout(
            connect=s.llm_connect_timeout,
            read=s.llm_stream_read_timeout,
            write=s.llm_connect_timeout,
            pool=s.llm_connect_timeout,
        )

    def _openai_chat_kwargs(
        self, ep: ModelEndpoint, messages: list[dict[str, str]], temperature: float, max_tokens: int
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": ep.model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if self._is_kimi_endpoint(ep):
            # 官方：勿显式传 temperature；关闭 thinking（stream/chat 一致，避免长时间无 delta）
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        else:
            kwargs["temperature"] = temperature
        return kwargs

    async def _openai_chat(
        self, ep: ModelEndpoint, messages: list[dict[str, str]], temperature: float, max_tokens: int
    ) -> ChatResult:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=ep.api_key or "sk-placeholder",
            base_url=ep.base_url,
            timeout=self._http_timeout(),
        )
        resp = await client.chat.completions.create(
            **self._openai_chat_kwargs(ep, messages, temperature, max_tokens)  # type: ignore[arg-type]
        )
        text = resp.choices[0].message.content or ""
        usage = resp.usage
        return ChatResult(
            text=text,
            input_tokens=int(usage.prompt_tokens) if usage else sum(count_tokens(m["content"]) for m in messages),
            output_tokens=int(usage.completion_tokens) if usage else count_tokens(text),
            provider=ep.provider,
            model=ep.model,
        )

    async def _openai_stream(
        self, ep: ModelEndpoint, messages: list[dict[str, str]], temperature: float, max_tokens: int
    ) -> AsyncIterator[dict[str, Any]]:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=ep.api_key or "sk-placeholder",
            base_url=ep.base_url,
            timeout=self._http_timeout(),
        )
        create_kwargs = self._openai_chat_kwargs(ep, messages, temperature, max_tokens)
        create_kwargs["stream"] = True
        if not self._is_kimi_endpoint(ep):
            create_kwargs["stream_options"] = {"include_usage": True}
        stream = await client.chat.completions.create(**create_kwargs)  # type: ignore[arg-type]
        parts: list[str] = []
        in_tok = sum(count_tokens(m["content"]) for m in messages)
        out_tok = 0
        async for event in stream:
            if event.usage:
                in_tok = int(event.usage.prompt_tokens or in_tok)
                out_tok = int(event.usage.completion_tokens or out_tok)
            if not event.choices:
                continue
            delta = event.choices[0].delta.content or ""
            if delta:
                parts.append(delta)
                yield {"delta_text": delta}
        text = "".join(parts)
        if not out_tok:
            out_tok = count_tokens(text)
        yield {
            "done": True,
            "text": text,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "provider": ep.provider,
            "model": ep.model,
        }

    async def _anthropic_chat(
        self, ep: ModelEndpoint, messages: list[dict[str, str]], temperature: float, max_tokens: int
    ) -> ChatResult:
        import anthropic

        client = anthropic.AsyncAnthropic(
            api_key=ep.api_key or "sk-ant-placeholder",
            base_url=ep.base_url or None,
            timeout=self._http_timeout(),
        )
        system, converted = self._split_system(messages)
        kwargs: dict[str, Any] = {
            "model": ep.model,
            "messages": converted,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if system:
            kwargs["system"] = system
        resp = await client.messages.create(**kwargs)
        text = "".join(b.text for b in resp.content if hasattr(b, "text"))
        return ChatResult(
            text=text,
            input_tokens=int(resp.usage.input_tokens),
            output_tokens=int(resp.usage.output_tokens),
            provider=ep.provider,
            model=ep.model,
        )

    async def _anthropic_stream(
        self, ep: ModelEndpoint, messages: list[dict[str, str]], temperature: float, max_tokens: int
    ) -> AsyncIterator[dict[str, Any]]:
        import anthropic

        client = anthropic.AsyncAnthropic(
            api_key=ep.api_key or "sk-ant-placeholder",
            base_url=ep.base_url or None,
            timeout=self._http_timeout(),
        )
        system, converted = self._split_system(messages)
        kwargs: dict[str, Any] = {
            "model": ep.model,
            "messages": converted,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if system:
            kwargs["system"] = system

        parts: list[str] = []
        in_tok = sum(count_tokens(m["content"]) for m in messages)
        out_tok = 0
        async with client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                parts.append(text)
                yield {"delta_text": text}
            final = await stream.get_final_message()
            in_tok = int(final.usage.input_tokens)
            out_tok = int(final.usage.output_tokens)
        yield {
            "done": True,
            "text": "".join(parts),
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "provider": ep.provider,
            "model": ep.model,
        }

    @staticmethod
    def _split_system(messages: list[dict[str, str]]) -> tuple[str, list[dict[str, Any]]]:
        system_parts: list[str] = []
        converted: list[dict[str, Any]] = []
        for m in messages:
            if m["role"] == "system":
                system_parts.append(m["content"])
            else:
                converted.append({"role": m["role"], "content": m["content"]})
        if not converted:
            converted = [{"role": "user", "content": "请继续。"}]
        return "\n\n".join(system_parts), converted


# ---- Mock 客户端（测试用）----

class MockLLMClient(LLMClient):
    """可注入响应的 Mock，用于单元测试。"""

    def __init__(
        self,
        chat_responses: Optional[list[str]] = None,
        stream_text: str = "这是生成的章节内容。",
        embed_dim: int = 8,
        smart: bool = True,
        stream_error: Optional[str] = None,
        stream_chunk_delay: float = 0.0,
    ) -> None:
        self.settings = get_settings()
        self.limiter = get_rate_limiter()
        self.chat_responses = list(chat_responses or [])
        self.stream_text = stream_text
        self.embed_dim = embed_dim
        self.smart = smart
        self.stream_error = stream_error
        self.stream_chunk_delay = stream_chunk_delay
        self._chat_idx = 0
        self.stream_calls: list[dict[str, Any]] = []

    def _smart_response(self, messages: list[dict[str, str]]) -> str:
        blob = "\n".join(m["content"] for m in messages)
        if "抽取" in blob or "characters" in blob and "world_settings" in blob:
            return json.dumps(
                {
                    "characters": [
                        {"name": "叶凡", "aliases": ["少年"], "role": "主角", "status": "凡人"}
                    ],
                    "world_settings": [
                        {
                            "category": "地理",
                            "title": "青阳城",
                            "content": "边陲城池",
                            "do_not_violate": "不可瞬移出城",
                        }
                    ],
                    "plot_threads": [
                        {
                            "title": "玉佩之谜",
                            "description": "发热玉佩",
                            "thread_type": "伏笔",
                            "status": "未回收",
                        }
                    ],
                },
                ensure_ascii=False,
            )
        if "大纲" in blob or "chapter_count" in blob or "续写大纲" in blob or "规划接下来" in blob:
            return json.dumps(
                {
                    "title": "青阳风云",
                    "items": [
                        {
                            "order": 1,
                            "title": "第四章 秘境",
                            "summary": "叶凡进入秘境",
                            "key_points": ["遇怪", "玉佩共鸣"],
                        }
                    ],
                },
                ensure_ascii=False,
            )
        if "一致性" in blob or '"ok"' in blob and "issues" in blob or "审查员" in blob:
            return json.dumps({"ok": True, "issues": []}, ensure_ascii=False)
        if "递归记忆" in blob or "ending_state" in blob or "更新递归记忆" in blob:
            return json.dumps(
                {
                    "ending_state": "叶凡在秘境入口",
                    "character_positions": {"叶凡": "秘境"},
                    "timeline_cursor": "入夜",
                    "open_threads": ["玉佩之谜"],
                },
                ensure_ascii=False,
            )
        if "文风" in blob or "samples" in blob and "代表性" in blob:
            return json.dumps(
                {"samples": [{"content": "少年叶凡醒来。", "reason": "开篇"}]},
                ensure_ascii=False,
            )
        if "卷级摘要" in blob or "卷名" in blob:
            return "卷摘要：叶凡入城遇苏婉。"
        if "概括" in blob or "摘要" in blob or "约300字" in blob:
            return "章摘要：叶凡持玉佩启程，抵达青阳城。"
        return "{}"

    async def chat(self, messages, *, endpoint=None, temperature=0.7, max_tokens=4096, purpose="chat") -> ChatResult:
        msgs = self._normalize(messages)
        if self.smart:
            text = self._smart_response(msgs)
        elif self.chat_responses:
            text = self.chat_responses[min(self._chat_idx, len(self.chat_responses) - 1)]
            self._chat_idx += 1
        else:
            text = "{}"
        ep = endpoint or self.summary_endpoint()
        return ChatResult(
            text=text,
            input_tokens=10,
            output_tokens=count_tokens(text),
            provider=ep.provider,
            model=ep.model,
        )
    async def stream(self, messages, *, endpoint=None, temperature=0.8, max_tokens=6000):
        import asyncio

        ep = endpoint or self.generation_endpoint()
        msgs = self._normalize(messages)
        self.stream_calls.append({"max_tokens": max_tokens, "messages": msgs})
        for ch in self.stream_text:
            if self.stream_chunk_delay > 0:
                await asyncio.sleep(self.stream_chunk_delay)
            yield {"delta_text": ch}
        if self.stream_error:
            raise RuntimeError(self.stream_error)
        yield {
            "done": True,
            "text": self.stream_text,
            "input_tokens": 10,
            "output_tokens": count_tokens(self.stream_text),
            "provider": ep.provider,
            "model": ep.model,
        }

    async def embed(self, texts: list[str]) -> tuple[list[list[float]], int]:
        vectors = []
        for i, t in enumerate(texts):
            base = float((hash(t) % 1000) / 1000.0)
            vectors.append([base + j * 0.01 for j in range(self.embed_dim)])
        return vectors, sum(count_tokens(t) for t in texts)


_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client


def set_llm_client(client: LLMClient) -> None:
    global _client
    _client = client
