"""进程内 asyncio 任务队列 + AsyncTask 状态机。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AsyncTask

logger = logging.getLogger(__name__)

TaskHandler = Callable[[AsyncSession, AsyncTask, "TaskProgress"], Awaitable[Any]]

# 进度落库时快速失败，避免与业务写事务形成「互相等待」式死锁
_PROGRESS_BUSY_TIMEOUT_MS = 100


def _is_db_locked(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "database is locked" in msg or "database is busy" in msg


class TaskProgress:
    def __init__(self, task_id: int) -> None:
        self.task_id = task_id
        self._subscribers: list[asyncio.Queue[dict[str, Any]]] = []
        self._last: dict[str, Any] = {
            "id": task_id,
            "status": "pending",
            "progress": 0.0,
            "message": "",
            "result": None,
            "error": None,
        }

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    def _merge_payload(
        self,
        *,
        progress: float | None,
        message: str | None,
        status: str | None,
        result: dict[str, Any] | None,
        error: str | None,
    ) -> dict[str, Any]:
        prev = self._last
        payload = {
            "id": self.task_id,
            "status": status if status is not None else prev.get("status"),
            "progress": (
                max(0.0, min(100.0, progress)) if progress is not None else prev.get("progress", 0.0)
            ),
            "message": message if message is not None else prev.get("message"),
            "result": result if result is not None else prev.get("result"),
            "error": error if error is not None else prev.get("error"),
        }
        self._last = payload
        return payload

    async def _notify(self, payload: dict[str, Any]) -> None:
        for q in list(self._subscribers):
            await q.put(payload)

    async def update(
        self,
        session: AsyncSession | None = None,
        *,
        progress: float | None = None,
        message: str | None = None,
        status: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        commit: bool = True,
    ) -> AsyncTask | None:
        """更新任务进度并推送给订阅者。

        默认用独立 session 写入进度，避免与业务事务共用 session.commit()
        破坏原子性。先推送内存/SSE，再尽力落库；若遇 database is locked
        （业务长事务持锁）则跳过落库，不抛错，避免与业务侧互相等待。
        """
        from app import db as db_mod

        payload = self._merge_payload(
            progress=progress,
            message=message,
            status=status,
            result=result,
            error=error,
        )
        # 先通知前端，不依赖 DB 写锁
        await self._notify(payload)

        async def _apply(s: AsyncSession, *, do_commit: bool) -> AsyncTask:
            task = await s.get(AsyncTask, self.task_id)
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
            if do_commit:
                await s.commit()
                await s.refresh(task)
            else:
                await s.flush()
            return task

        if not commit:
            if session is None:
                raise RuntimeError("commit=False 时必须提供 session")
            return await _apply(session, do_commit=False)

        if db_mod.SessionLocal is not None:
            try:
                async with db_mod.SessionLocal() as s:
                    # 短 timeout：持锁方若在等本协程，应立刻放弃落库而非死等
                    await s.execute(text(f"PRAGMA busy_timeout={_PROGRESS_BUSY_TIMEOUT_MS}"))
                    return await _apply(s, do_commit=True)
            except OperationalError as exc:
                if _is_db_locked(exc):
                    logger.warning(
                        "任务 %s 进度落库跳过（database locked）: %s / %s",
                        self.task_id,
                        payload.get("progress"),
                        payload.get("message"),
                    )
                    return None
                raise
            except Exception as exc:  # noqa: BLE001
                # aiosqlite 有时把 OperationalError 包在其它异常里
                if _is_db_locked(exc):
                    logger.warning(
                        "任务 %s 进度落库跳过（database locked）: %s / %s",
                        self.task_id,
                        payload.get("progress"),
                        payload.get("message"),
                    )
                    return None
                raise

        if session is not None:
            return await _apply(session, do_commit=True)
        raise RuntimeError("No session available for TaskProgress.update")


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
        result: dict[str, Any] | None = None,
    ) -> AsyncTask:
        if task_type not in self._handlers:
            raise ValueError(f"未知任务类型: {task_type}")
        task = AsyncTask(
            novel_id=novel_id,
            task_type=task_type,
            status="pending",
            progress=0.0,
            message=message,
            result=result,
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
                # 同步内存快照，供 locked 时 SSE 仍有正确基线
                progress._last = {
                    "id": task.id,
                    "status": task.status,
                    "progress": task.progress,
                    "message": task.message,
                    "result": task.result,
                    "error": task.error,
                }
                handler = self._handlers.get(task.task_type)
                if handler is None:
                    await progress.update(session, status="failed", error="无处理器", message="失败")
                    return
                await progress.update(session, status="running", progress=1.0, message="开始执行")
                try:
                    result = await handler(session, task, progress)
                    # 业务事务结束后再落终态，避免与未提交写锁冲突
                    if session.in_transaction():
                        await session.commit()
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
