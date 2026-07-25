"""限流 / 并发闸门 / 429 重试。"""

from __future__ import annotations

import asyncio

import pytest

from app.llm.rate_limiter import (
    ConcurrencyGate,
    is_rate_limit_error,
    is_retryable_error,
    parse_retry_after,
    reset_rate_limiter_state,
    with_retry,
)


def test_parse_retry_after_from_message():
    exc = Exception(
        "Error code: 429 - rate_limit_reached_error "
        "message: request reached max organization concurrency: 3, "
        "please try again after 1 seconds"
    )
    assert parse_retry_after(exc) == 1.0
    assert is_rate_limit_error(exc)
    assert is_retryable_error(exc)


def test_parse_retry_after_missing():
    assert parse_retry_after(Exception("boom")) is None
    assert not is_rate_limit_error(Exception("validation failed"))


@pytest.mark.asyncio
async def test_with_retry_respects_retry_after(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("app.llm.rate_limiter.asyncio.sleep", fake_sleep)

    calls = {"n": 0}

    async def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise Exception(
                "Error code: 429 - rate_limit_reached_error "
                "please try again after 1 seconds"
            )
        return "ok"

    result = await with_retry(flaky, max_retries=5, base_delay=0.1)
    assert result == "ok"
    assert calls["n"] == 3
    assert len(sleeps) == 2
    # 应至少等待服务端建议的 1s
    assert all(s >= 1.0 for s in sleeps)


@pytest.mark.asyncio
async def test_with_retry_does_not_retry_validation():
    calls = {"n": 0}

    async def bad() -> None:
        calls["n"] += 1
        raise ValueError("invalid json schema")

    with pytest.raises(ValueError):
        await with_retry(bad, max_retries=3, base_delay=0.01)
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_concurrency_gate_caps_inflight():
    reset_rate_limiter_state()
    gate = ConcurrencyGate(2)
    inflight = 0
    peak = 0
    lock = asyncio.Lock()

    async def worker() -> None:
        nonlocal inflight, peak
        async with gate:
            async with lock:
                inflight += 1
                peak = max(peak, inflight)
            await asyncio.sleep(0.05)
            async with lock:
                inflight -= 1

    await asyncio.gather(*(worker() for _ in range(8)))
    assert peak <= 2
