"""续写生成路由（SSE）。"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.models import Novel
from app.schemas.generation import BatchGenerateIn, BatchGenerateTaskOut, GenerateChapterIn
from app.services.batch_generation import BatchConflict, BatchNotFound, enqueue_batch_generate
from app.services.chapter_stream import DRAFT_INTERRUPTED, open_chapter_stream
from app.services.novel_role import REFERENCE_GENERATION_DETAIL, is_reference_role
from app.utils.sse import SSE_HEADERS, with_heartbeat

router = APIRouter(prefix="/api/novels/{novel_id}/generate", tags=["generation"])


def _sse_response(source: AsyncIterator[dict]) -> StreamingResponse:
    interval = get_settings().sse_heartbeat_interval
    return StreamingResponse(
        with_heartbeat(source, interval=interval),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


def _event_cursor(request: Request, after: int | None) -> int | None:
    raw = request.headers.get("last-event-id")
    header: int | None = None
    if raw:
        try:
            header = int(raw)
        except ValueError:
            header = None
    if after is None:
        return header
    if header is None:
        return after
    return max(header, after)


async def _chapter_events(
    *,
    novel_id: int,
    outline_item_id: int,
    run_critic: bool,
    max_critic_rounds: int,
    target_chars: int | None,
    cursor: int | None,
    allow_start: bool,
) -> AsyncIterator[dict]:
    stream = await open_chapter_stream(
        novel_id=novel_id,
        outline_item_id=outline_item_id,
        run_critic=run_critic,
        max_critic_rounds=max_critic_rounds,
        target_chars=target_chars,
        cursor=cursor,
        allow_start=allow_start,
    )
    if stream is None:
        yield {"event": "error", "message": DRAFT_INTERRUPTED, "draft_saved": True}
        return
    async for seq, evt in stream.subscribe(0 if cursor is None else cursor):
        yield {**evt, "_sse_id": seq}


@router.post("")
async def generate_chapter(
    novel_id: int,
    body: GenerateChapterIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    novel = await session.get(Novel, novel_id)
    if not novel:
        raise HTTPException(404, "小说不存在")
    if is_reference_role(novel.role):
        raise HTTPException(409, REFERENCE_GENERATION_DETAIL)

    cursor = _event_cursor(request, None)

    async def event_source():
        async for evt in _chapter_events(
            novel_id=novel_id,
            outline_item_id=body.outline_item_id,
            run_critic=body.run_critic,
            max_critic_rounds=body.max_critic_rounds,
            target_chars=body.target_chars,
            cursor=cursor,
            allow_start=True,
        ):
            yield evt

    return _sse_response(event_source())


@router.post("/batch", response_model=BatchGenerateTaskOut)
async def generate_batch(
    novel_id: int,
    body: BatchGenerateIn,
    session: AsyncSession = Depends(get_session),
):
    """入队连续生成。单章 SSE 接口不变。

    取消用现有 `POST /api/tasks/{task_id}/cancel`。正在写的一章会写完，下一章不再开始。
    Critic 未通过或某一章生成失败时，后续章节也不会再写。
    """
    from app.services.tasks import TaskDuplicateError

    try:
        task = await enqueue_batch_generate(
            session,
            novel_id,
            outline_id=body.outline_id,
            from_order=body.from_order,
            count=body.count,
            run_critic=body.run_critic,
            spot_check=body.spot_check,
        )
    except TaskDuplicateError as exc:
        raise HTTPException(409, str(exc)) from exc
    except BatchNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except BatchConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return BatchGenerateTaskOut(task_id=task.id, status=task.status)


@router.get("/stream")
async def generate_chapter_sse(
    novel_id: int,
    request: Request,
    outline_item_id: int = Query(...),
    run_critic: bool = Query(True),
    max_critic_rounds: int = Query(2, ge=0, le=2),
    target_chars: int | None = Query(default=None, ge=500, le=30000),
    after: int | None = Query(default=None),
    attach: bool = Query(default=False),
):
    """EventSource 友好的 GET SSE。attach=1 只接已有流，不新开一章。"""
    cursor = _event_cursor(request, after)

    async def event_source():
        async for evt in _chapter_events(
            novel_id=novel_id,
            outline_item_id=outline_item_id,
            run_critic=run_critic,
            max_critic_rounds=max_critic_rounds,
            target_chars=target_chars,
            cursor=cursor,
            allow_start=not attach,
        ):
            yield evt

    return _sse_response(event_source())
