"""小说与章节路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Chapter, ChapterVersion, Novel
from app.schemas.novel import (
    ChapterOut,
    ChapterPreview,
    ChapterReviseIn,
    ChapterVersionOut,
    ImportConfirmIn,
    ImportPreviewOut,
    NovelCreate,
    NovelOut,
    NovelUpdate,
)
from app.services import ingestion
from app.services.generation import revise_and_commit

router = APIRouter(prefix="/api/novels", tags=["novels"])


@router.get("", response_model=list[NovelOut])
async def list_novels(session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Novel).order_by(Novel.id.desc()))).scalars().all()
    return rows


@router.post("", response_model=NovelOut)
async def create_novel(body: NovelCreate, session: AsyncSession = Depends(get_session)):
    novel = Novel(**body.model_dump())
    session.add(novel)
    await session.commit()
    await session.refresh(novel)
    return novel


@router.get("/{novel_id}", response_model=NovelOut)
async def get_novel(novel_id: int, session: AsyncSession = Depends(get_session)):
    novel = await session.get(Novel, novel_id)
    if not novel:
        raise HTTPException(404, "小说不存在")
    return novel


@router.patch("/{novel_id}", response_model=NovelOut)
async def update_novel(novel_id: int, body: NovelUpdate, session: AsyncSession = Depends(get_session)):
    novel = await session.get(Novel, novel_id)
    if not novel:
        raise HTTPException(404, "小说不存在")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(novel, k, v)
    await session.commit()
    await session.refresh(novel)
    return novel


@router.delete("/{novel_id}")
async def delete_novel(novel_id: int, session: AsyncSession = Depends(get_session)):
    novel = await session.get(Novel, novel_id)
    if not novel:
        raise HTTPException(404, "小说不存在")
    await session.delete(novel)
    await session.commit()
    return {"message": "已删除"}


@router.post("/import/preview", response_model=ImportPreviewOut)
async def import_preview(
    file: UploadFile | None = File(None),
    files: list[UploadFile] | None = File(None),
    title: str = Form("未命名小说"),
):
    if files:
        payload = []
        for f in files:
            data = await f.read()
            payload.append((f.filename or "chapter.txt", data))
        return ingestion.preview_from_files(payload, suggested_title=title)
    if file is None:
        raise HTTPException(400, "请上传文件")
    raw = await file.read()
    name = file.filename or title
    suggested = title if title != "未命名小说" else name.rsplit(".", 1)[0]
    return ingestion.preview_from_text(raw, suggested_title=suggested)


@router.post("/import/confirm", response_model=NovelOut)
async def import_confirm(body: ImportConfirmIn, session: AsyncSession = Depends(get_session)):
    try:
        novel = await ingestion.confirm_import(
            session,
            import_token=body.import_token,
            title=body.title,
            author=body.author,
            genre=body.genre,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return novel


@router.post("/{novel_id}/ingest")
async def start_ingest(novel_id: int, session: AsyncSession = Depends(get_session)):
    try:
        task = await ingestion.start_ingestion(session, novel_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return {"task_id": task.id, "status": task.status}


@router.get("/{novel_id}/chapters", response_model=list[ChapterOut])
async def list_chapters(novel_id: int, session: AsyncSession = Depends(get_session)):
    rows = (
        await session.execute(
            select(Chapter).where(Chapter.novel_id == novel_id).order_by(Chapter.index)
        )
    ).scalars().all()
    return [
        ChapterOut(
            id=c.id,
            novel_id=c.novel_id,
            index=c.index,
            title=c.title,
            volume=c.volume,
            char_count=c.char_count,
            status=c.status,
            is_generated=c.is_generated,
            content=None,
        )
        for c in rows
    ]


@router.get("/{novel_id}/chapters/{chapter_id}", response_model=ChapterOut)
async def get_chapter(novel_id: int, chapter_id: int, session: AsyncSession = Depends(get_session)):
    ch = await session.get(Chapter, chapter_id)
    if not ch or ch.novel_id != novel_id:
        raise HTTPException(404, "章节不存在")
    return ChapterOut(
        id=ch.id,
        novel_id=ch.novel_id,
        index=ch.index,
        title=ch.title,
        volume=ch.volume,
        char_count=ch.char_count,
        status=ch.status,
        is_generated=ch.is_generated,
        content=ch.content,
    )


@router.get("/{novel_id}/chapters/{chapter_id}/versions", response_model=list[ChapterVersionOut])
async def list_versions(novel_id: int, chapter_id: int, session: AsyncSession = Depends(get_session)):
    ch = await session.get(Chapter, chapter_id)
    if not ch or ch.novel_id != novel_id:
        raise HTTPException(404, "章节不存在")
    rows = (
        await session.execute(
            select(ChapterVersion)
            .where(ChapterVersion.chapter_id == chapter_id)
            .order_by(ChapterVersion.id)
        )
    ).scalars().all()
    return rows


@router.post("/{novel_id}/chapters/{chapter_id}/revise", response_model=ChapterVersionOut)
async def revise_chapter(
    novel_id: int,
    chapter_id: int,
    body: ChapterReviseIn,
    session: AsyncSession = Depends(get_session),
):
    ch = await session.get(Chapter, chapter_id)
    if not ch or ch.novel_id != novel_id:
        raise HTTPException(404, "章节不存在")
    ver = await revise_and_commit(
        session, chapter_id, body.content, commit_to_knowledge=body.commit_to_knowledge
    )
    return ver
