"""任务、成本、配置路由。"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.models import AsyncTask, CostLog
from app.schemas.tasks import (
    ConfigOut,
    CostSummaryOut,
    PurposeTokenOut,
    StageRouteOut,
    TaskOut,
)
from app.services.llm_profiles import effective_llm
from app.services.tasks import TaskNotFound, TaskStateError, get_task_queue

router = APIRouter(prefix="/api", tags=["tasks"])


def _key_configured(api_key: str | None) -> bool:
    """占位 sk-your-* 视为未配置；anonymous/none 等免费匿名档视为已配置。"""
    key = (api_key or "").strip()
    if not key or key.startswith("sk-your"):
        return False
    return True


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(
    novel_id: int | None = None,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
):
    return await get_task_queue().list_tasks(session, novel_id=novel_id, limit=limit)


@router.get("/tasks/{task_id}", response_model=TaskOut)
async def get_task(task_id: int, session: AsyncSession = Depends(get_session)):
    task = await session.get(AsyncTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


@router.post("/tasks/{task_id}/cancel", response_model=TaskOut)
async def cancel_task(task_id: int, session: AsyncSession = Depends(get_session)):
    try:
        return await get_task_queue().cancel(session, task_id)
    except TaskNotFound:
        raise HTTPException(404, "任务不存在") from None
    except TaskStateError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/tasks/{task_id}/retry", response_model=TaskOut)
async def retry_task(task_id: int, session: AsyncSession = Depends(get_session)):
    try:
        return await get_task_queue().retry(session, task_id)
    except TaskNotFound:
        raise HTTPException(404, "任务不存在") from None
    except TaskStateError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/tasks/{task_id}/events")
async def task_events(task_id: int, session: AsyncSession = Depends(get_session)):
    task = await session.get(AsyncTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")

    progress = get_task_queue().get_progress(task_id)
    queue = progress.subscribe()

    async def event_stream():
        # 先推当前状态
        yield f"data: {json.dumps({'id': task.id, 'status': task.status, 'progress': task.progress, 'message': task.message, 'result': task.result, 'error': task.error}, ensure_ascii=False)}\n\n"
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    # 轮询兜底
                    from app import db as db_mod

                    if db_mod.SessionLocal:
                        async with db_mod.SessionLocal() as s:
                            t = await s.get(AsyncTask, task_id)
                            if t and t.status in ("completed", "failed", "cancelled"):
                                yield f"data: {json.dumps({'id': t.id, 'status': t.status, 'progress': t.progress, 'message': t.message, 'result': t.result, 'error': t.error}, ensure_ascii=False)}\n\n"
                                break
                    continue
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                if payload.get("status") in ("completed", "failed", "cancelled"):
                    break
        finally:
            progress.unsubscribe(queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/costs", response_model=CostSummaryOut)
async def cost_summary(novel_id: int | None = None, session: AsyncSession = Depends(get_session)):
    def _scoped(stmt):
        if novel_id is not None:
            return stmt.where(CostLog.novel_id == novel_id)
        return stmt

    total_cost = await session.scalar(
        _scoped(select(func.coalesce(func.sum(CostLog.cost_usd), 0.0)))
    )
    total_in = await session.scalar(
        _scoped(select(func.coalesce(func.sum(CostLog.input_tokens), 0)))
    )
    total_out = await session.scalar(
        _scoped(select(func.coalesce(func.sum(CostLog.output_tokens), 0)))
    )
    purpose_rows = (
        await session.execute(
            _scoped(
                select(
                    CostLog.purpose,
                    func.coalesce(func.sum(CostLog.cost_usd), 0.0),
                    func.coalesce(func.sum(CostLog.input_tokens), 0),
                    func.coalesce(func.sum(CostLog.output_tokens), 0),
                ).group_by(CostLog.purpose)
            )
        )
    ).all()
    by_purpose = {str(purpose): float(cost or 0.0) for purpose, cost, _in, _out in purpose_rows}
    by_purpose_tokens = {
        str(purpose): PurposeTokenOut(
            input_tokens=int(in_tok or 0),
            output_tokens=int(out_tok or 0),
            cost_usd=round(float(cost or 0.0), 6),
        )
        for purpose, cost, in_tok, out_tok in purpose_rows
    }

    recent_stmt = _scoped(select(CostLog)).order_by(CostLog.id.desc()).limit(30)
    rows = (await session.execute(recent_stmt)).scalars().all()
    recent = [
        {
            "id": r.id,
            "purpose": r.purpose,
            "model": r.model,
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "cost_usd": r.cost_usd,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return CostSummaryOut(
        total_cost_usd=round(float(total_cost or 0.0), 6),
        total_input_tokens=int(total_in or 0),
        total_output_tokens=int(total_out or 0),
        by_purpose=by_purpose,
        by_purpose_tokens=by_purpose_tokens,
        recent=recent,
    )


def _stage_routes(s) -> list[StageRouteOut]:
    return [
        StageRouteOut(
            stage="summary",
            label="摘要 / 抽取",
            provider=s.summary_provider,
            model=s.summary_model,
            purposes=["summary", "extract", "memory", "style"],
        ),
        StageRouteOut(
            stage="generation",
            label="大纲 / 续写",
            provider=s.generation_provider,
            model=s.generation_model,
            purposes=["outline", "generation"],
        ),
        StageRouteOut(
            stage="critic",
            label="审校 Critic",
            provider=s.summary_provider,
            model=s.summary_model,
            purposes=["critic", "consistency"],
        ),
        StageRouteOut(
            stage="embedding",
            label="向量化",
            provider="openai",
            model=s.embedding_model,
            purposes=["embed"],
        ),
    ]


@router.get("/config", response_model=ConfigOut)
async def get_config():
    base = get_settings()
    s = effective_llm()
    return ConfigOut(
        summary_provider=s.summary_provider,
        summary_model=s.summary_model,
        generation_provider=s.generation_provider,
        generation_model=s.generation_model,
        embedding_model=s.embedding_model,
        context_token_budget=base.context_token_budget,
        generation_max_tokens=base.generation_max_tokens,
        chapter_segment_threshold=base.chapter_segment_threshold,
        segment_target_chars=base.segment_target_chars,
        has_summary_key=_key_configured(s.summary_api_key),
        has_generation_key=_key_configured(s.generation_api_key),
        has_embedding_key=_key_configured(s.embedding_api_key),
        stage_routes=_stage_routes(s),
    )
