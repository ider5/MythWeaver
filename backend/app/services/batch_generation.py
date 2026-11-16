"""导演模式：按已确认大纲连续生成若干章。

复用 `stream_generate_chapter`，不改单章 SSE。进度写在 AsyncTask.result。

取消：仓库里还没有任务取消 API，队列在处理器返回后也会把状态写成 completed。
因此本任务不能中途取消；某一章生成失败，或 Critic 报告未通过时，停在下一章之前。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AsyncTask, Novel, Outline, OutlineItem
from app.services.generation import resolve_target_chapter_index, stream_generate_chapter

logger = logging.getLogger(__name__)

BATCH_TASK_TYPE = "batch_generate"


class BatchNotFound(ValueError):
    """小说或大纲不存在。"""


def critic_gate_reason(consistency: dict[str, Any] | None, *, run_critic: bool) -> str | None:
    """Critic 未通过时返回暂停原因。警告且 ok 仍为真时继续。"""
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
    if consistency.get("ok") is False or errors:
        message = ""
        if errors:
            message = str(errors[0].get("message") or "").strip()
        if not message:
            message = "一致性未通过"
        return f"Critic 未通过：{message}"
    return None


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
    items: list[dict[str, Any]] = [dict(row) for row in (payload.get("items") or [])]
    if not novel_id or not outline_id or not items:
        raise ValueError("连续生成任务缺少大纲范围")

    from app import db as db_mod

    if db_mod.SessionLocal is None:
        raise RuntimeError("数据库未初始化")

    paused = False
    pause_reason: str | None = None

    for index, row in enumerate(items):
        row["status"] = "running"
        row["message"] = "生成中"
        pct = round(index / max(len(items), 1) * 100, 1)
        snapshot = _snapshot(
            novel_id=novel_id,
            outline_id=outline_id,
            from_order=from_order,
            count=count or len(items),
            run_critic=run_critic,
            items=items,
            paused=False,
            pause_reason=None,
        )
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
                    run_critic=run_critic,
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
            failed = _snapshot(
                novel_id=novel_id,
                outline_id=outline_id,
                from_order=from_order,
                count=count or len(items),
                run_critic=run_critic,
                items=items,
                paused=False,
                pause_reason=None,
            )
            await progress.update(session, message=str(exc), result=failed)
            raise RuntimeError(row["message"]) from exc

        consistency = done.get("consistency") if isinstance(done.get("consistency"), dict) else None
        row["chapter_id"] = done.get("chapter_id")
        row["consistency_ok"] = None if consistency is None else bool(consistency.get("ok"))
        gate = critic_gate_reason(consistency, run_critic=run_critic)
        if gate:
            row["status"] = "paused"
            row["message"] = gate
            paused = True
            pause_reason = gate
            _block_rest(items, index + 1, "前序章节未通过 Critic，已停下")
            break

        row["status"] = "done"
        row["message"] = "已完成"

    return _snapshot(
        novel_id=novel_id,
        outline_id=outline_id,
        from_order=from_order,
        count=count or len(items),
        run_critic=run_critic,
        items=items,
        paused=paused,
        pause_reason=pause_reason,
    )
