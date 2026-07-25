"""SSE 格式化与心跳：避免代理/浏览器在长时间无数据时断开连接。"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import suppress
from typing import Any

logger = logging.getLogger(__name__)

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def format_sse(data: Mapping[str, Any] | None = None, *, comment: str | None = None) -> str:
    if comment is not None:
        return f": {comment}\n\n"
    assert data is not None
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def with_heartbeat(
    source: AsyncIterator[dict[str, Any]],
    *,
    interval: float = 12.0,
) -> AsyncIterator[str]:
    """包装事件字典迭代器：空闲超过 interval 秒则发 ping，异常则发 error 并结束。"""
    it = source.__aiter__()
    pending: asyncio.Task[dict[str, Any]] = asyncio.create_task(anext(it))
    try:
        while True:
            done, _ = await asyncio.wait({pending}, timeout=interval)
            if not done:
                yield format_sse(comment="ping")
                yield format_sse({"event": "ping"})
                continue
            try:
                evt = pending.result()
            except StopAsyncIteration:
                break
            except Exception as exc:  # noqa: BLE001
                logger.exception("SSE source raised")
                yield format_sse({"event": "error", "message": f"生成失败: {exc}"})
                break
            yield format_sse(evt)
            if evt.get("event") in ("done", "error"):
                break
            pending = asyncio.create_task(anext(it))
    finally:
        if not pending.done():
            pending.cancel()
            with suppress(asyncio.CancelledError, StopAsyncIteration, Exception):
                await pending
        aclose = getattr(it, "aclose", None)
        if callable(aclose):
            with suppress(Exception):
                await aclose()
