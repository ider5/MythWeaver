"""进程内 asyncio 任务队列 + AsyncTask 状态机。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AsyncTask

logger = logging.getLogger(__name__)

TaskHandler = Callable[[AsyncSession, AsyncTask, "TaskProgress"], Awaitable[Any]]

# 进度落库时快速失败，避免与业务写事务形成「互相等待」式死锁
_PROGRESS_BUSY_TIMEOUT_MS = 100

_TERMINAL = frozenset({"completed", "failed", "cancelled"})


class TaskNotFound(Exception):
    pass


class TaskStateError(Exception):
    pass


class TaskCancelled(Exception):
    """协作式取消。处理器在检查点抛出后，任务记为 cancelled。"""


class TaskDuplicateError(Exception):
    """同书同类型仍有排队/执行中的任务时拒绝再入队。"""

    def __init__(self, existing: AsyncTask):
        self.existing = existing
        super().__init__(
            f"已有进行中的「{existing.task_type}」任务 #{existing.id}，请等待完成或取消后再试"
        )


def _is_db_locked(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "database is locked" in msg or "database is busy" in msg


def _snapshot(task: AsyncTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "status": task.status,
        "progress": task.progress,
        "message": task.message,
        "result": task.result,
        "error": task.error,
    }


async def _release_ingest_novel(session: AsyncSession, task: AsyncTask) -> None:
    """入库未完成时把小说从 ingesting 放回 imported，便于重试。"""
    if task.task_type != "ingest" or task.novel_id is None:
        return
    if task.status not in ("failed", "cancelled"):
        return
    from app.models import Novel

    novel = await session.get(Novel, task.novel_id)
    if novel is not None and novel.status == "ingesting":
        novel.status = "imported"


class TaskProgress:
    def __init__(self, task_id: int) -> None:
        self.task_id = task_id
        self._cancel_requested = False
        self._subscribers: list[asyncio.Queue[dict[str, Any]]] = []
        self._last: dict[str, Any] = {
            "id": task_id,
            "status": "pending",
            "progress": 0.0,
            "message": "",
            "result": None,
            "error": None,
        }

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_requested

    def request_cancel(self) -> None:
        self._cancel_requested = True

    def raise_if_cancelled(self) -> None:
        if self._cancel_requested:
            raise TaskCancelled("任务已取消")

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    def sync_from_task(self, task: AsyncTask) -> None:
        self._last = _snapshot(task)

    async def publish_snapshot(self, task: AsyncTask) -> None:
        payload = _snapshot(task)
        self._last = payload
        await self._notify(payload)

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

        已请求取消时，进度心跳会抛出 TaskCancelled，让协作式处理器停下来。
        显式写入 completed / failed / cancelled 不受此限制。
        """
        from app import db as db_mod

        if self._cancel_requested and status not in _TERMINAL:
            raise TaskCancelled("任务已取消")

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
            if task.status == "cancelled" and status != "cancelled":
                self.request_cancel()
                raise TaskCancelled("任务已取消")
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
            except TaskCancelled:
                raise
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

    async def find_active(
        self,
        session: AsyncSession,
        *,
        task_type: str,
        novel_id: int | None,
    ) -> AsyncTask | None:
        """同书同类型的 pending/running 任务（若有）。"""
        stmt = select(AsyncTask).where(
            AsyncTask.task_type == task_type,
            AsyncTask.status.in_(("pending", "running")),
        )
        if novel_id is None:
            stmt = stmt.where(AsyncTask.novel_id.is_(None))
        else:
            stmt = stmt.where(AsyncTask.novel_id == novel_id)
        stmt = stmt.order_by(AsyncTask.id.desc()).limit(1)
        return await session.scalar(stmt)

    async def enqueue(
        self,
        session: AsyncSession,
        *,
        task_type: str,
        novel_id: int | None = None,
        message: str = "排队中",
        result: dict[str, Any] | None = None,
        allow_duplicate: bool = False,
    ) -> AsyncTask:
        if task_type not in self._handlers:
            raise ValueError(f"未知任务类型: {task_type}")
        if not allow_duplicate:
            existing = await self.find_active(session, task_type=task_type, novel_id=novel_id)
            if existing is not None:
                raise TaskDuplicateError(existing)
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

    async def cancel(self, session: AsyncSession, task_id: int) -> AsyncTask:
        """请求取消排队中或执行中的任务。已取消的再次调用直接返回。"""
        task = await session.get(AsyncTask, task_id)
        if task is None:
            raise TaskNotFound()
        if task.status in ("completed", "failed"):
            raise TaskStateError("任务已结束，无法取消")
        if task.status == "cancelled":
            return task

        progress = self.get_progress(task_id)
        progress.request_cancel()
        if task.status == "pending" and task_id not in self._running:
            task.status = "cancelled"
            task.message = "已取消"
            task.error = None
            task.updated_at = datetime.utcnow()
            await _release_ingest_novel(session, task)
            await session.commit()
            await session.refresh(task)
            await progress.publish_snapshot(task)
            return task

        # 执行中的任务只改文案。条件更新避免把已经落成 cancelled 的行写回 running。
        await session.execute(
            update(AsyncTask)
            .where(
                AsyncTask.id == task_id,
                AsyncTask.status.in_(("pending", "running")),
            )
            .values(message="正在取消", updated_at=datetime.utcnow())
        )
        await session.commit()
        session.expire(task)
        await session.refresh(task)
        await progress.publish_snapshot(task)
        return task

    async def retry(self, session: AsyncSession, task_id: int) -> AsyncTask:
        """按原参数重新入队。入库会重新调用入库管线。"""
        task = await session.get(AsyncTask, task_id)
        if task is None:
            raise TaskNotFound()
        if task.status not in ("failed", "cancelled"):
            raise TaskStateError("只有失败或已取消的任务可以重试")
        if not task.can_retry():
            raise TaskStateError("该任务无法重试")

        if task.task_type == "ingest":
            active = (
                await session.execute(
                    select(AsyncTask.id)
                    .where(
                        AsyncTask.novel_id == task.novel_id,
                        AsyncTask.task_type == "ingest",
                        AsyncTask.status.in_(("pending", "running")),
                    )
                    .limit(1)
                )
            ).first()
            if active is not None:
                raise TaskStateError("已有进行中的入库任务")
            from app.services.ingestion import start_ingestion

            try:
                return await start_ingestion(session, int(task.novel_id))
            except ValueError as exc:
                raise TaskStateError(str(exc)) from exc

        if task.task_type == "revise_commit":
            payload = task.result or {}
            from app.services.generation import enqueue_revise_commit

            version_id = payload.get("version_id")
            try:
                new_id = await enqueue_revise_commit(
                    session,
                    int(payload["chapter_id"]),
                    version_id=int(version_id) if version_id is not None else None,
                )
            except ValueError as exc:
                raise TaskStateError(str(exc)) from exc
            created = await session.get(AsyncTask, new_id)
            if created is None:
                raise TaskStateError("重试任务创建失败")
            return created

        if task.task_type == "outline_generate":
            payload = dict(task.result or {})
            from app.services.outline import enqueue_outline_generate

            start = payload.get("start_from_chapter")
            try:
                return await enqueue_outline_generate(
                    session,
                    int(task.novel_id),
                    chapter_count=int(payload.get("chapter_count") or 5),
                    guidance=payload.get("guidance"),
                    start_from_chapter=int(start) if start is not None else None,
                )
            except ValueError as exc:
                raise TaskStateError(str(exc)) from exc

        raise TaskStateError("该任务无法重试")

    async def _persist_terminal(
        self,
        task_id: int,
        progress: TaskProgress,
        *,
        status: str,
        message: str,
        error: str | None = None,
        set_error: bool = False,
        progress_value: float | None = None,
        result: dict[str, Any] | None = None,
    ) -> None:
        from app import db as db_mod

        if db_mod.SessionLocal is None:
            return
        async with db_mod.SessionLocal() as session:
            task = await session.get(AsyncTask, task_id)
            if task is None:
                return
            if task.status == "completed":
                await progress.publish_snapshot(task)
                return
            if task.status == "cancelled" and status != "cancelled":
                await progress.publish_snapshot(task)
                return
            task.status = status
            task.message = message
            if progress_value is not None:
                task.progress = progress_value
            if result is not None:
                task.result = result
            if set_error:
                task.error = error
            task.updated_at = datetime.utcnow()
            if status in ("failed", "cancelled"):
                await _release_ingest_novel(session, task)
            await session.commit()
            await session.refresh(task)
            await progress.publish_snapshot(task)

    async def _finish_cancelled(self, task_id: int, progress: TaskProgress) -> None:
        await self._persist_terminal(
            task_id,
            progress,
            status="cancelled",
            message="已取消",
            error=None,
            set_error=True,
        )

    async def _finish_failed(
        self,
        task_id: int,
        progress: TaskProgress,
        *,
        error: str,
        message: str | None = None,
    ) -> None:
        from app import db as db_mod

        if progress.cancel_requested:
            await self._finish_cancelled(task_id, progress)
            return
        msg = message
        if msg is None and db_mod.SessionLocal is not None:
            async with db_mod.SessionLocal() as session:
                task = await session.get(AsyncTask, task_id)
                if task is not None and task.can_retry():
                    msg = "失败，可重试"
        if msg is None:
            msg = "失败"
        await self._persist_terminal(
            task_id,
            progress,
            status="failed",
            message=msg,
            error=error,
            set_error=True,
            progress_value=100.0,
        )

    async def _run(self, task_id: int) -> None:
        async with self._lock:
            if task_id in self._running:
                return
            self._running.add(task_id)

        from app import db as db_mod

        progress = self.get_progress(task_id)
        try:
            if db_mod.SessionLocal is None:
                return
            async with db_mod.SessionLocal() as session:
                task = await session.get(AsyncTask, task_id)
                if task is None:
                    return
                progress.sync_from_task(task)
                if task.status == "cancelled" or progress.cancel_requested:
                    await self._finish_cancelled(task_id, progress)
                    return
                handler = self._handlers.get(task.task_type)
                if handler is None:
                    await self._finish_failed(
                        task_id, progress, error="无处理器", message="失败"
                    )
                    return
                try:
                    await progress.update(session, status="running", progress=1.0, message="开始执行")
                    result = await handler(session, task, progress)
                    # 业务事务结束后再落终态，避免与未提交写锁冲突
                    if session.in_transaction():
                        await session.commit()
                    if progress.cancel_requested:
                        raise TaskCancelled("任务已取消")
                    payload = result if isinstance(result, dict) else {"ok": True}
                    await progress.update(
                        session,
                        status="completed",
                        progress=100.0,
                        message="完成",
                        result=payload,
                    )
                except TaskCancelled:
                    logger.info("任务 %s 已取消", task_id)
                    await session.rollback()
                    await self._finish_cancelled(task_id, progress)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("任务 %s 失败", task_id)
                    await session.rollback()
                    if progress.cancel_requested:
                        await self._finish_cancelled(task_id, progress)
                    else:
                        await self._finish_failed(task_id, progress, error=str(exc))
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


async def fail_interrupted_tasks(session: AsyncSession) -> int:
    """进程重启后把未完成任务标为失败，并清掉卡在 generating 的书/大纲条目。

    SSE 续写不是 AsyncTask；若不复位，重启后 novels/outline_items 会一直 generating。
    """
    from app.models import Novel, OutlineItem

    rows = (
        await session.execute(
            select(AsyncTask).where(AsyncTask.status.in_(("pending", "running")))
        )
    ).scalars().all()
    for task in rows:
        task.status = "failed"
        task.error = "interrupted by restart"
        task.message = "进程重启，任务已中断"
        await _release_ingest_novel(session, task)

    stuck_novels = (
        await session.execute(select(Novel).where(Novel.status == "generating"))
    ).scalars().all()
    for novel in stuck_novels:
        novel.status = "ready"

    stuck_items = (
        await session.execute(select(OutlineItem).where(OutlineItem.status == "generating"))
    ).scalars().all()
    for item in stuck_items:
        item.status = "pending"

    await session.commit()
    return len(rows) + len(stuck_novels) + len(stuck_items)


_queue: TaskQueue | None = None


def get_task_queue() -> TaskQueue:
    global _queue
    if _queue is None:
        _queue = TaskQueue()
    return _queue
