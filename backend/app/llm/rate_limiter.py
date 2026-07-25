"""RPM/TPM 限流 + 指数退避重试。"""

from __future__ import annotations

import asyncio
import random
import time
from collections import deque
from typing import Awaitable, Callable, TypeVar

from app.config import get_settings

T = TypeVar("T")


class RateLimiter:
    def __init__(self, rpm: int | None = None, tpm: int | None = None) -> None:
        settings = get_settings()
        self.rpm = rpm or settings.llm_rpm
        self.tpm = tpm or settings.llm_tpm
        self._request_times: deque[float] = deque()
        self._token_events: deque[tuple[float, int]] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self, estimated_tokens: int = 1000) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._prune(now)
                if len(self._request_times) < self.rpm and self._tokens_in_window() + estimated_tokens <= self.tpm:
                    self._request_times.append(now)
                    self._token_events.append((now, estimated_tokens))
                    return
                wait = 0.2
                if self._request_times:
                    wait = max(wait, 60.0 - (now - self._request_times[0]) + 0.05)
                await asyncio.sleep(min(wait, 2.0))

    def _prune(self, now: float) -> None:
        while self._request_times and now - self._request_times[0] > 60:
            self._request_times.popleft()
        while self._token_events and now - self._token_events[0][0] > 60:
            self._token_events.popleft()

    def _tokens_in_window(self) -> int:
        return sum(t for _, t in self._token_events)


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
            if attempt >= retries:
                break
            delay = base_delay * (2**attempt) + random.uniform(0, 0.5)
            await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc


_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter()
    return _limiter
