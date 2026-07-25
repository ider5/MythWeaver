"""进程内 asyncio 任务队列 + AsyncTask 状态机。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AsyncTask

logger = logging.getLogger(__name__)

TaskHandler = Callable[[AsyncSession, AsyncTask, "TaskProgress"], Awaitable[Any]]


class TaskProgress:
    def __init__(self, task_id: int) -> None:
        self.task_id = task_id
        self._subscribers: list[asyncio.Queue[dict[str, Any]]] = []

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    async def update(
        self,
        session: AsyncSession,
        *,
        progress: float | None = None,
        message: str | None = None,
        status: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> AsyncTask:
        task = await session.get(AsyncTask, self.task_id)
        if task is None:
            raise RuntimeError(f"Task {self.task_id} not found")
        if progress is not None:
            task.progress = max(0.0, min(100.0, progress))
        if message is not None:
            task.message = message
        if status is not None:
            task.status = status
        if result is not None:
            task.result = result
        if error is not None:
            task.error = error
        task.updated_at = datetime.utcnow()
        await session.commit()
        await session.refresh(task)
        payload = {
            "id": task.id,
            "status": task.status,
            "progress": task.progress,
            "message": task.message,
            "result": task.result,
            "error": task.error,
        }
        for q in list(self._subscribers):
            await q.put(payload)
        return task


class TaskQueue:
    def __init__(self) -> None:
        self._handlers: dict[str, TaskHandler] = {}
        self._progress: dict[int, TaskProgress] = {}
        self._running: set[int] = set()
        self._bg_tasks: dict[int, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    def register(self, task_type: str, handler: TaskHandler) -> None:
        self._handlers[task_type] = handler

    def get_progress(self, task_id: int) -> TaskProgress:
        if task_id not in self._progress:
            self._progress[task_id] = TaskProgress(task_id)
        return self._progress[task_id]

    async def enqueue(
        self,
        session: AsyncSession,
        *,
        task_type: str,
        novel_id: int | None = None,
        message: str = "排队中",
    ) -> AsyncTask:
        if task_type not in self._handlers:
            raise ValueError(f"未知任务类型: {task_type}")
        task = AsyncTask(
            novel_id=novel_id,
            task_type=task_type,
            status="pending",
            progress=0.0,
            message=message,
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        self.get_progress(task.id)
        bg = asyncio.create_task(self._run(task.id))
        self._bg_tasks[task.id] = bg
        bg.add_done_callback(lambda _t, tid=task.id: self._bg_tasks.pop(tid, None))
        return task

    async def wait_task(self, task_id: int, timeout: float = 120.0) -> None:
        bg = self._bg_tasks.get(task_id)
        if bg is not None:
            await asyncio.wait_for(bg, timeout=timeout)
            return
        # 任务可能已跑完，直接返回
        return

    async def _run(self, task_id: int) -> None:
        async with self._lock:
            if task_id in self._running:
                return
            self._running.add(task_id)

        from app import db as db_mod

        if db_mod.SessionLocal is None:
            return
        progress = self.get_progress(task_id)
        try:
            async with db_mod.SessionLocal() as session:
                task = await session.get(AsyncTask, task_id)
                if task is None:
                    return
                handler = self._handlers.get(task.task_type)
                if handler is None:
                    await progress.update(session, status="failed", error="无处理器", message="失败")
                    return
                await progress.update(session, status="running", progress=1.0, message="开始执行")
                try:
                    result = await handler(session, task, progress)
                    if isinstance(result, dict):
                        await progress.update(
                            session, status="completed", progress=100.0, message="完成", result=result
                        )
                    else:
                        await progress.update(
                            session, status="completed", progress=100.0, message="完成", result={"ok": True}
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.exception("任务 %s 失败", task_id)
                    await session.rollback()
                    async with db_mod.SessionLocal() as s2:
                        await progress.update(
                            s2, status="failed", message="失败", error=str(exc), progress=100.0
                        )
        finally:
            async with self._lock:
                self._running.discard(task_id)

    async def list_tasks(
        self, session: AsyncSession, *, novel_id: int | None = None, limit: int = 50
    ) -> list[AsyncTask]:
        stmt = select(AsyncTask).order_by(AsyncTask.id.desc()).limit(limit)
        if novel_id is not None:
            stmt = stmt.where(AsyncTask.novel_id == novel_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())


_queue: TaskQueue | None = None


def get_task_queue() -> TaskQueue:
    global _queue
    if _queue is None:
        _queue = TaskQueue()
    return _queue
