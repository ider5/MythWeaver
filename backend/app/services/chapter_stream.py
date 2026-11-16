"""单章生成与 HTTP 连接分开：断线后按序号接上，生成继续跑。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

logger = logging.getLogger(__name__)

DRAFT_INTERRUPTED = "生成已中断。已写完的段落还在章节里，刷新后可以接着改。"

_TERMINAL = frozenset({"done", "error"})


class LiveChapterStream:
    def __init__(self) -> None:
        self.events: list[tuple[int, dict[str, Any]]] = []
        self.subscribers: list[asyncio.Queue] = []
        self.done = False
        self._seq = 0
        self.task: asyncio.Task | None = None

    def publish(self, evt: dict[str, Any]) -> int:
        self._seq += 1
        stored = dict(evt)
        self.events.append((self._seq, stored))
        if stored.get("event") in _TERMINAL:
            self.done = True
        for queue in list(self.subscribers):
            queue.put_nowait((self._seq, stored))
        return self._seq

    def finish(self) -> None:
        self.done = True
        for queue in list(self.subscribers):
            queue.put_nowait(None)

    def replay(self, after: int) -> list[tuple[int, dict[str, Any]]]:
        missed = [(seq, evt) for seq, evt in self.events if seq > after]
        if missed:
            return missed
        if self.done and self.events:
            seq, evt = self.events[-1]
            if evt.get("event") in _TERMINAL:
                return [(seq, evt)]
        return []

    async def subscribe(self, after: int) -> AsyncIterator[tuple[int, dict[str, Any]]]:
        queue: asyncio.Queue = asyncio.Queue()
        self.subscribers.append(queue)
        seen = after
        try:
            for seq, evt in self.replay(after):
                seen = seq
                yield seq, evt
                if evt.get("event") in _TERMINAL:
                    return
            if self.done:
                return
            while True:
                item = await queue.get()
                if item is None:
                    return
                seq, evt = item
                if seq <= seen:
                    continue
                seen = seq
                yield seq, evt
                if evt.get("event") in _TERMINAL:
                    return
        finally:
            if queue in self.subscribers:
                self.subscribers.remove(queue)


_live: dict[tuple[int, int], LiveChapterStream] = {}
_guard = asyncio.Lock()


def reset_chapter_streams() -> None:
    _live.clear()


async def open_chapter_stream(
    *,
    novel_id: int,
    outline_item_id: int,
    run_critic: bool,
    max_critic_rounds: int,
    target_chars: int | None,
    cursor: int | None,
    allow_start: bool,
) -> LiveChapterStream | None:
    """有进行中的流就接上。带了断点序号或 attach 时，不再新开一章。"""
    key = (novel_id, outline_item_id)
    async with _guard:
        current = _live.get(key)
        if current is not None and not current.done:
            return current
        if cursor is not None or not allow_start:
            return current if current is not None else None
        stream = LiveChapterStream()
        _live[key] = stream

        async def _drive() -> None:
            from app import db as db_mod
            from app.services.generation import stream_generate_chapter

            try:
                if db_mod.SessionLocal is None:
                    stream.publish({"event": "error", "message": "数据库未初始化"})
                    return
                async with db_mod.SessionLocal() as session:
                    async for evt in stream_generate_chapter(
                        session,
                        novel_id,
                        outline_item_id,
                        run_critic=run_critic,
                        max_critic_rounds=max_critic_rounds,
                        target_chars=target_chars,
                    ):
                        stream.publish(evt)
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "chapter stream failed novel=%s item=%s", novel_id, outline_item_id
                )
                if not stream.done:
                    stream.publish({"event": "error", "message": f"生成失败: {exc}"})
            finally:
                stream.finish()

        stream.task = asyncio.create_task(_drive())
        return stream
