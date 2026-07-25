"""SSE 心跳 / 错误事件 / 流中断。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.utils.sse import format_sse, with_heartbeat


async def _collect(agen: AsyncIterator[str], limit: int = 50) -> list[str]:
    out: list[str] = []
    async for chunk in agen:
        out.append(chunk)
        if len(out) >= limit:
            break
    return out


def _parse_data_events(chunks: list[str]) -> list[dict[str, Any]]:
    events = []
    for c in chunks:
        if c.startswith("data: "):
            events.append(json.loads(c[len("data: ") :].strip()))
    return events


@pytest.mark.asyncio
async def test_heartbeat_emits_ping_when_idle():
    async def slow_source() -> AsyncIterator[dict[str, Any]]:
        await asyncio.sleep(0.35)
        yield {"event": "status", "message": "ok"}
        yield {"event": "done", "content": "x"}

    chunks = await _collect(with_heartbeat(slow_source(), interval=0.1))
    assert any(c.startswith(": ping") for c in chunks)
    events = _parse_data_events(chunks)
    assert any(e.get("event") == "ping" for e in events)
    assert events[-1]["event"] == "done"


@pytest.mark.asyncio
async def test_source_exception_becomes_error_event():
    async def boom() -> AsyncIterator[dict[str, Any]]:
        yield {"event": "status", "message": "start"}
        raise RuntimeError("upstream cut")

    chunks = await _collect(with_heartbeat(boom(), interval=5.0))
    events = _parse_data_events(chunks)
    assert events[0]["event"] == "status"
    assert events[-1]["event"] == "error"
    assert "upstream cut" in events[-1]["message"]
    assert not any(e.get("event") == "done" for e in events)


@pytest.mark.asyncio
async def test_error_event_from_source_ends_stream():
    async def failing() -> AsyncIterator[dict[str, Any]]:
        yield {"event": "delta", "text": "半"}
        yield {"event": "error", "message": "模型超时"}

    chunks = await _collect(with_heartbeat(failing(), interval=5.0))
    events = _parse_data_events(chunks)
    assert events[-1] == {"event": "error", "message": "模型超时"}


@pytest.mark.asyncio
async def test_mock_stream_error_surfaces_as_sse_error():
    """模拟上游流中断：经 with_heartbeat 应得到明确 error 事件。"""
    from app.llm.client import MockLLMClient

    client = MockLLMClient(stream_text="半截", stream_error="connection reset", smart=False)

    async def source() -> AsyncIterator[dict[str, Any]]:
        try:
            async for chunk in client.stream([{"role": "user", "content": "写"}]):
                if "delta_text" in chunk:
                    yield {"event": "delta", "text": chunk["delta_text"]}
                if chunk.get("done"):
                    yield {"event": "done", "content": chunk.get("text")}
        except Exception as exc:  # noqa: BLE001
            yield {"event": "error", "message": f"生成失败: {exc}"}

    chunks = await _collect(with_heartbeat(source(), interval=5.0))
    events = _parse_data_events(chunks)
    assert any(e.get("event") == "delta" for e in events)
    assert events[-1]["event"] == "error"
    assert "connection reset" in events[-1]["message"]


def test_format_sse_comment_and_data():
    assert format_sse(comment="ping") == ": ping\n\n"
    line = format_sse({"event": "ping"})
    assert line.startswith("data: ")
    assert json.loads(line[6:].strip()) == {"event": "ping"}
