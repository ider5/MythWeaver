"""RPM/TPM 限流 + 并发闸门 + 指数退避重试。"""

from __future__ import annotations

import asyncio
import random
import re
import time
from collections import deque
from typing import Awaitable, Callable, TypeVar

from app.config import get_settings

T = TypeVar("T")

# "please try again after 1 seconds" / "retry after 2.5s"
_RETRY_AFTER_RE = re.compile(
    r"(?:try again|retry)\s+after\s+(\d+(?:\.\d+)?)\s*(?:seconds?|s)\b",
    re.IGNORECASE,
)


class RateLimiter:
    def __init__(self, rpm: int | None = None, tpm: int | None = None) -> None:
        settings = get_settings()
        self.rpm = rpm or settings.llm_rpm
        self.tpm = tpm or settings.llm_tpm
        self._request_times: deque[float] = deque()
        self._token_events: deque[tuple[float, int]] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self, estimated_tokens: int = 1000) -> None:
        # 睡眠必须在锁外，否则限流等待会堵死所有其它 acquire
        while True:
            async with self._lock:
                now = time.monotonic()
                self._prune(now)
                if len(self._request_times) < self.rpm and self._tokens_in_window() + estimated_tokens <= self.tpm:
                    self._request_times.append(now)
                    self._token_events.append((now, estimated_tokens))
                    return
                wait = 0.2
                if self._request_times:
                    wait = max(wait, 60.0 - (now - self._request_times[0]) + 0.05)
                wait = min(wait, 2.0)
            await asyncio.sleep(wait)

    def _prune(self, now: float) -> None:
        while self._request_times and now - self._request_times[0] > 60:
            self._request_times.popleft()
        while self._token_events and now - self._token_events[0][0] > 60:
            self._token_events.popleft()

    def _tokens_in_window(self) -> int:
        return sum(t for _, t in self._token_events)


class ConcurrencyGate:
    """限制同时进行的 in-flight 请求数（组织并发上限场景）。"""

    def __init__(self, limit: int) -> None:
        self.limit = max(1, limit)
        self._sem = asyncio.Semaphore(self.limit)

    async def __aenter__(self) -> ConcurrencyGate:
        await self._sem.acquire()
        return self

    async def __aexit__(self, *args: object) -> None:
        self._sem.release()


def parse_retry_after(exc: BaseException) -> float | None:
    """从错误信息或响应头解析建议等待秒数。"""
    msg = str(exc)
    m = _RETRY_AFTER_RE.search(msg)
    if m:
        return float(m.group(1))

    response = getattr(exc, "response", None)
    if response is not None:
        headers = getattr(response, "headers", None) or {}
        ra = None
        if hasattr(headers, "get"):
            ra = headers.get("retry-after") or headers.get("Retry-After")
        if ra is not None:
            try:
                return float(ra)
            except (TypeError, ValueError):
                pass
    return None


def is_rate_limit_error(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(exc, "status", None)
    if status == 429:
        return True
    name = type(exc).__name__.lower()
    if "ratelimit" in name:
        return True
    msg = str(exc).lower()
    return (
        "rate_limit" in msg
        or "rate limit" in msg
        or "rate_limit_reached" in msg
        or "organization concurrency" in msg
        or "error code: 429" in msg
    )


def is_retryable_error(exc: BaseException) -> bool:
    if is_rate_limit_error(exc):
        return True
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if isinstance(status, int) and status in {408, 409, 425, 500, 502, 503, 504}:
        return True
    name = type(exc).__name__.lower()
    if any(k in name for k in ("timeout", "connection", "apiconnection", "internalserver")):
        return True
    msg = str(exc).lower()
    return any(k in msg for k in ("timeout", "temporarily unavailable", "connection reset", "overloaded"))


async def with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    max_retries: int | None = None,
    base_delay: float = 1.0,
) -> T:
    settings = get_settings()
    retries = max_retries if max_retries is not None else settings.llm_max_retries
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return await fn()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt >= retries or not is_retryable_error(exc):
                break
            delay = base_delay * (2**attempt) + random.uniform(0, 0.5)
            retry_after = parse_retry_after(exc)
            if retry_after is not None:
                # 尊重服务端建议，并加少量 jitter，避免惊群
                delay = max(delay, retry_after + random.uniform(0.05, 0.35))
            elif is_rate_limit_error(exc):
                # 429 无明确等待时间时，至少多等一会
                delay = max(delay, base_delay * (2**attempt) + random.uniform(0.5, 1.5))
            await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc


_limiter: RateLimiter | None = None
_llm_gate: ConcurrencyGate | None = None
_embedding_gate: ConcurrencyGate | None = None


def get_rate_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter()
    return _limiter


def get_llm_concurrency_gate() -> ConcurrencyGate:
    """chat/stream 全局并发（SUMMARY 与 GENERATION 共用，适配组织并发上限）。"""
    global _llm_gate
    if _llm_gate is None:
        _llm_gate = ConcurrencyGate(get_settings().llm_max_concurrency)
    return _llm_gate


def get_embedding_concurrency_gate() -> ConcurrencyGate:
    """向量化独立闸门（常为另一家厂商，与 chat 并发解耦）。"""
    global _embedding_gate
    if _embedding_gate is None:
        _embedding_gate = ConcurrencyGate(get_settings().embedding_max_concurrency)
    return _embedding_gate


def reset_rate_limiter_state() -> None:
    """测试用：清空单例。"""
    global _limiter, _llm_gate, _embedding_gate
    _limiter = None
    _llm_gate = None
    _embedding_gate = None
