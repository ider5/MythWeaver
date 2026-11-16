"""导演模式：按已确认大纲连续生成若干章。

复用 `stream_generate_chapter`，不改单章 SSE。进度写在 AsyncTask.result。

取消走现有 `POST /api/tasks/{id}/cancel`。正在写的一章会写完，下一章开始前停下。
某一章生成失败、Critic 出现严重问题、篇幅偏离目标，或章末没落到悬念钩子时，不再写后面的章。
文风漂移、伏笔提醒和其它警告只记在这一章上，连续生成继续。
`spot_check` 为真时，完整 Critic 只跑首章、末章和每隔 3 章。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AsyncTask, Novel, Outline, OutlineItem
from app.services.generation import resolve_target_chapter_index, stream_generate_chapter
from app.services.novel_role import REFERENCE_GENERATION_DETAIL, is_reference_role
from app.services.quality_loop import blocking_message, chapters_for_full_critic

logger = logging.getLogger(__name__)

BATCH_TASK_TYPE = "batch_generate"


class BatchNotFound(ValueError):
    """小说或大纲不存在。"""


class BatchConflict(ValueError):
    """请求与当前小说角色或进行中的生成冲突。"""


def critic_gate_reason(consistency: dict[str, Any] | None, *, run_critic: bool) -> str | None:
    """完整 Critic 出现 severity=error，或没有报告时暂停。warning 继续写。"""
    if not run_critic:
        return None
    if not consistency:
        return "未得到一致性报告，已暂停后续章节"
    issues = consistency.get("issues") or []
    errors = [
        issue
        for issue in issues
        if str(issue.get("severity") or "").lower() == "error"
    ]
    if not errors:
        return None
    message = str(errors[0].get("message") or "").strip() or "一致性未通过"
    return f"Critic 未通过：{message}"


def _quality_hints(quality: dict[str, Any] | None) -> list[dict[str, Any]]:
    hints = (quality or {}).get("hints") if isinstance(quality, dict) else None
    if not isinstance(hints, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for hint in hints:
        if not isinstance(hint, dict):
            continue
        cleaned.append(
            {
                "id": hint.get("id"),
                "kind": hint.get("kind"),
                "severity": hint.get("severity"),
                "message": hint.get("message") or "",
            }
        )
    return cleaned


def completion_note(quality: dict[str, Any] | None, consistency: dict[str, Any] | None) -> str:
    """已完成章节上要露出来的非严重提示。"""
    notes: list[str] = []
    for hint in _quality_hints(quality):
        if str(hint.get("severity") or "").lower() == "error":
            continue
        message = str(hint.get("message") or "").strip()
        if message:
            notes.append(message)
    for issue in (consistency or {}).get("issues") or []:
        if not isinstance(issue, dict):
            continue
        if str(issue.get("severity") or "").lower() != "warning":
            continue
        message = str(issue.get("message") or "").strip()
        if message:
            notes.append(message)
    if not notes:
        return "已完成"
    shown = notes[:2]
    text = "；".join(shown)
    extra = len(notes) - len(shown)
    if extra:
        text += f"；另有 {extra} 条"
    return f"已完成 · {text}"


def _item_row(item: OutlineItem, *, start_from_chapter: int) -> dict[str, Any]:
    return {
        "order": item.order,
        "outline_item_id": item.id,
        "title": item.title or "",
        "chapter_index": resolve_target_chapter_index(
            start_from_chapter=start_from_chapter,
            order=item.order,
        ),
        "status": "queued",
        "chapter_id": None,
        "consistency_ok": None,
        "message": "",
    }


def _snapshot(
    *,
    novel_id: int,
    outline_id: int,
    from_order: int,
    count: int,
    run_critic: bool,
    spot_check: bool,
    items: list[dict[str, Any]],
    paused: bool,
    pause_reason: str | None,
) -> dict[str, Any]:
    done = sum(1 for row in items if row.get("status") == "done")
    if paused:
        summary = pause_reason or "已暂停"
    elif any(row.get("status") == "failed" for row in items):
        failed = next(row for row in items if row.get("status") == "failed")
        summary = str(failed.get("message") or "生成失败")
    else:
        summary = f"已连续生成 {done} 章"
    return {
        "kind": BATCH_TASK_TYPE,
        "novel_id": novel_id,
        "outline_id": outline_id,
        "from_order": from_order,
        "count": count,
        "run_critic": run_critic,
        "spot_check": spot_check,
        "paused": paused,
        "pause_reason": pause_reason,
        "summary": summary,
        "items": items,
    }


async def _load_outline_items(session: AsyncSession, outline_id: int) -> list[OutlineItem]:
    rows = (
        await session.execute(
            select(OutlineItem)
            .where(OutlineItem.outline_id == outline_id)
            .order_by(OutlineItem.order)
        )
    ).scalars().all()
    return list(rows)


async def plan_batch_items(
    session: AsyncSession,
    novel_id: int,
    *,
    outline_id: int,
    from_order: int,
    count: int,
) -> tuple[Outline, list[OutlineItem]]:
    novel = await session.get(Novel, novel_id)
    if novel is None:
        raise BatchNotFound("小说不存在")
    if is_reference_role(novel.role):
        raise BatchConflict(REFERENCE_GENERATION_DETAIL)
    outline = await session.get(Outline, outline_id)
    if outline is None or outline.novel_id != novel_id:
        raise BatchNotFound("大纲不存在")
    if outline.status != "confirmed":
        raise ValueError("请先确认大纲，再连续生成")
    if novel.status == "generating":
        raise ValueError("小说正在生成中，请稍后再试")

    by_order = {item.order: item for item in await _load_outline_items(session, outline_id)}
    selected: list[OutlineItem] = []
    missing: list[int] = []
    for offset in range(count):
        order = from_order + offset
        item = by_order.get(order)
        if item is None:
            missing.append(order)
        else:
            selected.append(item)
    if missing:
        joined = "、".join(str(order) for order in missing)
        raise ValueError(f"大纲缺少连续序号 {joined}，无法生成 {count} 章")

    busy = [item.order for item in selected if item.status == "generating"]
    if busy:
        raise ValueError(f"序号 {busy[0]} 正在生成，请稍后再试")

    running = await session.scalar(
        select(func.count())
        .select_from(AsyncTask)
        .where(
            AsyncTask.novel_id == novel_id,
            AsyncTask.task_type == BATCH_TASK_TYPE,
            AsyncTask.status.in_(("pending", "running")),
        )
    )
    if running:
        raise ValueError("已有连续生成任务在进行")
    return outline, selected


async def enqueue_batch_generate(
    session: AsyncSession,
    novel_id: int,
    *,
    outline_id: int,
    from_order: int,
    count: int,
    run_critic: bool = True,
    spot_check: bool = False,
) -> AsyncTask:
    outline, selected = await plan_batch_items(
        session,
        novel_id,
        outline_id=outline_id,
        from_order=from_order,
        count=count,
    )
    from app.services.tasks import get_task_queue

    result = _snapshot(
        novel_id=novel_id,
        outline_id=outline.id,
        from_order=from_order,
        count=count,
        run_critic=run_critic,
        spot_check=spot_check,
        items=[_item_row(item, start_from_chapter=outline.start_from_chapter) for item in selected],
        paused=False,
        pause_reason=None,
    )
    return await get_task_queue().enqueue(
        session,
        task_type=BATCH_TASK_TYPE,
        novel_id=novel_id,
        message=f"连续生成 {count} 章排队中",
        result=result,
    )


async def consume_generated_chapter(
    session: AsyncSession,
    novel_id: int,
    outline_item_id: int,
    *,
    run_critic: bool,
) -> dict[str, Any]:
    """跑完现有单章生成流，只取终态。正文不进入任务结果。"""
    done: dict[str, Any] | None = None
    error: str | None = None
    async for evt in stream_generate_chapter(
        session,
        novel_id,
        outline_item_id,
        run_critic=run_critic,
        max_critic_rounds=2,
    ):
        kind = evt.get("event")
        if kind == "done":
            done = evt
        elif kind == "error":
            error = str(evt.get("message") or "生成失败")
    if done is not None:
        return done
    raise RuntimeError(error or "生成失败")


def _block_rest(items: list[dict[str, Any]], start: int, message: str) -> None:
    for row in items[start:]:
        if row.get("status") == "queued":
            row["status"] = "blocked"
            row["message"] = message


async def batch_generate_handler(session: AsyncSession, task: AsyncTask, progress: Any) -> dict[str, Any]:
    payload = dict(task.result or {})
    novel_id = int(payload.get("novel_id") or task.novel_id or 0)
    outline_id = int(payload.get("outline_id") or 0)
    from_order = int(payload.get("from_order") or 1)
    count = int(payload.get("count") or 0)
    run_critic = bool(payload.get("run_critic", True))
    spot_check = bool(payload.get("spot_check", False))
    items: list[dict[str, Any]] = [dict(row) for row in (payload.get("items") or [])]
    if not novel_id or not outline_id or not items:
        raise ValueError("连续生成任务缺少大纲范围")
    full_indexes = chapters_for_full_critic(len(items), spot_check=spot_check)

    from app import db as db_mod

    if db_mod.SessionLocal is None:
        raise RuntimeError("数据库未初始化")

    from app.services.tasks import TaskCancelled

    paused = False
    pause_reason: str | None = None

    def _current_snapshot(*, paused: bool = False, pause_reason: str | None = None) -> dict[str, Any]:
        return _snapshot(
            novel_id=novel_id,
            outline_id=outline_id,
            from_order=from_order,
            count=count or len(items),
            run_critic=run_critic,
            spot_check=spot_check,
            items=items,
            paused=paused,
            pause_reason=pause_reason,
        )

    for index, row in enumerate(items):
        if getattr(progress, "cancel_requested", False):
            _block_rest(items, index, "已取消，后续不再生成")
            await progress.update(
                session,
                status="cancelled",
                message="已取消",
                result=_current_snapshot(),
            )
            raise TaskCancelled("任务已取消")

        row["status"] = "running"
        row["message"] = "生成中"
        pct = round(index / max(len(items), 1) * 100, 1)
        snapshot = _current_snapshot()
        await progress.update(
            session,
            progress=max(pct, 1.0),
            message=f"正在生成第 {index + 1}/{len(items)} 章…",
            result=snapshot,
        )

        try:
            async with db_mod.SessionLocal() as chapter_session:
                done = await consume_generated_chapter(
                    chapter_session,
                    novel_id,
                    int(row["outline_item_id"]),
                    run_critic=run_critic and index in full_indexes,
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "batch chapter failed novel=%s item=%s",
                novel_id,
                row.get("outline_item_id"),
            )
            row["status"] = "failed"
            row["message"] = str(exc)
            _block_rest(items, index + 1, "前序章节生成失败，已停下")
            await progress.update(session, message=str(exc), result=_current_snapshot())
            raise RuntimeError(row["message"]) from exc

        if getattr(progress, "cancel_requested", False):
            row["status"] = "done"
            row["chapter_id"] = done.get("chapter_id")
            row["message"] = "已完成"
            _block_rest(items, index + 1, "已取消，后续不再生成")
            await progress.update(
                session,
                status="cancelled",
                message="已取消",
                result=_current_snapshot(),
            )
            raise TaskCancelled("任务已取消")

        consistency = done.get("consistency") if isinstance(done.get("consistency"), dict) else None
        quality = done.get("quality") if isinstance(done.get("quality"), dict) else None
        full_critic = run_critic and index in full_indexes
        row["chapter_id"] = done.get("chapter_id")
        row["consistency_ok"] = None if consistency is None else bool(consistency.get("ok"))
        row["spot_checked"] = full_critic
        row["quality_hints"] = _quality_hints(quality)
        gate = critic_gate_reason(consistency, run_critic=full_critic) or blocking_message(quality)
        if gate:
            row["status"] = "paused"
            row["message"] = gate
            paused = True
            pause_reason = gate
            blocked = "前序章节未通过质量检查，已停下"
            _block_rest(items, index + 1, blocked)
            break

        row["status"] = "done"
        row["message"] = completion_note(quality, consistency)

    return _snapshot(
        novel_id=novel_id,
        outline_id=outline_id,
        from_order=from_order,
        count=count or len(items),
        run_critic=run_critic,
        spot_check=spot_check,
        items=items,
        paused=paused,
        pause_reason=pause_reason,
    )
