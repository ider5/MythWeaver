"""双协议统一 LLM 客户端：openai | anthropic，统一 chat/stream/embed。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal, Optional

from app.config import Provider, get_settings
from app.llm.rate_limiter import get_rate_limiter, with_retry
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

        return await with_retry(_call)

    async def stream(
        self,
        messages: list[ChatMessage] | list[dict[str, str]],
        *,
        endpoint: ModelEndpoint | None = None,
        temperature: float = 0.8,
        max_tokens: int = 6000,
    ) -> AsyncIterator[dict[str, Any]]:
        """流式增量统一为 {delta_text}，结束时 yield {done, text, input_tokens, output_tokens}。"""
        ep = endpoint or self.generation_endpoint()
        msgs = self._normalize(messages)
        est = sum(count_tokens(m["content"]) for m in msgs) + max_tokens
        await self.limiter.acquire(est)

        if ep.provider == "anthropic":
            async for chunk in self._anthropic_stream(ep, msgs, temperature, max_tokens):
                yield chunk
        else:
            async for chunk in self._openai_stream(ep, msgs, temperature, max_tokens):
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
            resp = await client.embeddings.create(model=s.embedding_model, input=texts)
            vectors = [item.embedding for item in resp.data]
            tokens = getattr(resp.usage, "total_tokens", est) if resp.usage else est
            return vectors, int(tokens)

        return await with_retry(_call)

    def _normalize(self, messages: list[ChatMessage] | list[dict[str, str]]) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for m in messages:
            if isinstance(m, ChatMessage):
                out.append({"role": m.role, "content": m.content})
            else:
                out.append({"role": m["role"], "content": m["content"]})
        return out

    async def _openai_chat(
        self, ep: ModelEndpoint, messages: list[dict[str, str]], temperature: float, max_tokens: int
    ) -> ChatResult:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=ep.api_key or "sk-placeholder", base_url=ep.base_url)
        resp = await client.chat.completions.create(
            model=ep.model,
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature,
            max_tokens=max_tokens,
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

        client = AsyncOpenAI(api_key=ep.api_key or "sk-placeholder", base_url=ep.base_url)
        stream = await client.chat.completions.create(
            model=ep.model,
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            stream_options={"include_usage": True},
        )
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

        client = anthropic.AsyncAnthropic(api_key=ep.api_key or "sk-ant-placeholder", base_url=ep.base_url or None)
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

        client = anthropic.AsyncAnthropic(api_key=ep.api_key or "sk-ant-placeholder", base_url=ep.base_url or None)
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
    ) -> None:
        self.settings = get_settings()
        self.limiter = get_rate_limiter()
        self.chat_responses = list(chat_responses or [])
        self.stream_text = stream_text
        self.embed_dim = embed_dim
        self.smart = smart
        self._chat_idx = 0

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
        ep = endpoint or self.generation_endpoint()
        for ch in self.stream_text:
            yield {"delta_text": ch}
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
