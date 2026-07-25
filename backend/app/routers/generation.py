"""续写生成路由（SSE）。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Novel
from app.schemas.generation import GenerateChapterIn
from app.services.generation import stream_generate_chapter

router = APIRouter(prefix="/api/novels/{novel_id}/generate", tags=["generation"])


@router.post("")
async def generate_chapter(
    novel_id: int,
    body: GenerateChapterIn,
    session: AsyncSession = Depends(get_session),
):
    novel = await session.get(Novel, novel_id)
    if not novel:
        raise HTTPException(404, "小说不存在")

    async def event_stream():
        from app import db as db_mod

        assert db_mod.SessionLocal
        async with db_mod.SessionLocal() as s:
            async for evt in stream_generate_chapter(
                s,
                novel_id,
                body.outline_item_id,
                run_critic=body.run_critic,
                max_critic_rounds=body.max_critic_rounds,
            ):
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/stream")
async def generate_chapter_sse(
    novel_id: int,
    outline_item_id: int = Query(...),
    run_critic: bool = Query(True),
    max_critic_rounds: int = Query(2),
):
    """EventSource 友好的 GET SSE。"""

    async def event_stream():
        from app import db as db_mod

        assert db_mod.SessionLocal
        async with db_mod.SessionLocal() as s:
            novel = await s.get(Novel, novel_id)
            if not novel:
                yield f"data: {json.dumps({'event': 'error', 'message': '小说不存在'}, ensure_ascii=False)}\n\n"
                return
            async for evt in stream_generate_chapter(
                s,
                novel_id,
                outline_item_id,
                run_critic=run_critic,
                max_critic_rounds=max_critic_rounds,
            ):
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
