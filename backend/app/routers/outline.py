"""大纲路由。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Novel
from app.schemas.outline import (
    OutlineDeleteOut,
    OutlineGenerateIn,
    OutlineGenerateTaskOut,
    OutlineOut,
    OutlineUpdateIn,
)
from app.services import outline as outline_svc

router = APIRouter(prefix="/api/novels/{novel_id}/outlines", tags=["outline"])


@router.get("", response_model=list[OutlineOut])
async def list_outlines(novel_id: int, session: AsyncSession = Depends(get_session)):
    novel = await session.get(Novel, novel_id)
    if not novel:
        raise HTTPException(404, "小说不存在")
    return await outline_svc.list_outlines(session, novel_id)


@router.post("/generate", response_model=OutlineGenerateTaskOut)
async def generate(novel_id: int, body: OutlineGenerateIn, session: AsyncSession = Depends(get_session)):
    """入队异步大纲生成，前端通过 /api/tasks/{id}/events 跟踪进度。"""
    try:
        task = await outline_svc.enqueue_outline_generate(
            session,
            novel_id,
            chapter_count=body.chapter_count,
            guidance=body.guidance,
            start_from_chapter=body.start_from_chapter,
        )
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return OutlineGenerateTaskOut(task_id=task.id, status=task.status)


@router.get("/{outline_id}", response_model=OutlineOut)
async def get_one(novel_id: int, outline_id: int, session: AsyncSession = Depends(get_session)):
    try:
        outline = await outline_svc.get_outline(session, outline_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    if outline.novel_id != novel_id:
        raise HTTPException(404, "大纲不存在")
    return outline


@router.put("/{outline_id}", response_model=OutlineOut)
async def update(
    novel_id: int,
    outline_id: int,
    body: OutlineUpdateIn,
    session: AsyncSession = Depends(get_session),
):
    try:
        outline = await outline_svc.get_outline(session, outline_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    if outline.novel_id != novel_id:
        raise HTTPException(404, "大纲不存在")
    items = [i.model_dump() for i in body.items] if body.items is not None else None
    return await outline_svc.update_outline(session, outline_id, title=body.title, items=items)


@router.post("/{outline_id}/confirm", response_model=OutlineOut)
async def confirm(novel_id: int, outline_id: int, session: AsyncSession = Depends(get_session)):
    try:
        outline = await outline_svc.get_outline(session, outline_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    if outline.novel_id != novel_id:
        raise HTTPException(404, "大纲不存在")
    return await outline_svc.confirm_outline(session, outline_id)


@router.delete("/{outline_id}", response_model=OutlineDeleteOut)
async def delete_outline(
    novel_id: int,
    outline_id: int,
    session: AsyncSession = Depends(get_session),
):
    """删除大纲（draft/confirmed 均可）。

    已生成章节正文保留，仅解除与大纲条目的关联。
    """
    try:
        outline = await outline_svc.get_outline(session, outline_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    if outline.novel_id != novel_id:
        raise HTTPException(404, "大纲不存在")
    result = await outline_svc.delete_outline(session, outline_id)
    return OutlineDeleteOut(
        message=result["message"],
        outline_id=result["outline_id"],
        unbound_chapters=result["unbound_chapters"],
    )
