"""小说与章节路由。"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Chapter, ChapterVersion, Novel
from app.schemas.novel import (
    ChapterOut,
    ChapterPreview,
    ChapterReviseIn,
    ChapterReviseOut,
    ChapterVersionOut,
    CommitKnowledgeOut,
    ImportConfirmIn,
    ImportPreviewOut,
    NovelCreate,
    NovelOut,
    NovelUpdate,
)
from app.services import ingestion
from app.services.chapter_length import refresh_original_chapter_stats
from app.services.generation import (
    delete_chapter,
    delete_chapter_version,
    enqueue_revise_commit,
    find_chapter_by_outline_item,
    revise_and_commit,
)

router = APIRouter(prefix="/api/novels", tags=["novels"])


def _safe_filename(title: str, ext: str) -> str:
    name = (title or "未命名").strip() or "未命名"
    for ch in '\\/:*?"<>|\r\n':
        name = name.replace(ch, "_")
    return f"{name}.{ext}"


def _content_disposition(filename: str, ext: str) -> str:
    """ASCII fallback + RFC 5987，兼容中文书名。"""
    ascii_name = f"novel.{ext}"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def _build_export_text(chapters: list[Chapter], fmt: str) -> str:
    parts: list[str] = []
    for ch in chapters:
        title = (ch.title or "").strip() or f"第{ch.index}章"
        body = ch.content or ""
        if fmt == "md":
            block = f"# {title}\n\n{body}".rstrip()
        else:
            block = f"{title}\n\n{body}".rstrip()
        parts.append(block)
    return "\n\n".join(parts)


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
    if (novel.median_chapter_chars or 0) <= 0 and (novel.avg_chapter_chars or 0) <= 0:
        await refresh_original_chapter_stats(session, novel)
        await session.commit()
        await session.refresh(novel)
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


@router.get("/{novel_id}/export")
async def export_novel(
    novel_id: int,
    fmt: str = Query("txt", alias="format"),
    session: AsyncSession = Depends(get_session),
):
    """导出小说当前章节正文为 txt / md 文件下载。"""
    fmt = (fmt or "txt").lower().strip()
    if fmt not in ("txt", "md"):
        raise HTTPException(400, "format 仅支持 txt 或 md")

    novel = await session.get(Novel, novel_id)
    if not novel:
        raise HTTPException(404, "小说不存在")

    chapters = (
        await session.execute(
            select(Chapter).where(Chapter.novel_id == novel_id).order_by(Chapter.index)
        )
    ).scalars().all()

    body = _build_export_text(list(chapters), fmt)
    filename = _safe_filename(novel.title, fmt)
    media = "text/markdown; charset=utf-8" if fmt == "md" else "text/plain; charset=utf-8"
    return Response(
        content=body.encode("utf-8"),
        media_type=media,
        headers={"Content-Disposition": _content_disposition(filename, fmt)},
    )


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
            outline_item_id=c.outline_item_id,
            content=None,
        )
        for c in rows
    ]


@router.get("/{novel_id}/chapters/by-outline-item/{outline_item_id}", response_model=ChapterOut)
async def get_chapter_by_outline_item(
    novel_id: int,
    outline_item_id: int,
    session: AsyncSession = Depends(get_session),
):
    """按大纲条目取已生成章节正文（续写页刷新回载用）。

    若 outline_item_id 因删大纲/重建而解绑，按目标章号回退查找并重新绑定。
    """
    ch = await find_chapter_by_outline_item(
        session, novel_id=novel_id, outline_item_id=outline_item_id
    )
    if not ch:
        raise HTTPException(404, "该大纲条目尚无已生成章节")
    return ChapterOut(
        id=ch.id,
        novel_id=ch.novel_id,
        index=ch.index,
        title=ch.title,
        volume=ch.volume,
        char_count=ch.char_count,
        status=ch.status,
        is_generated=ch.is_generated,
        outline_item_id=ch.outline_item_id,
        content=ch.content,
    )


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
        outline_item_id=ch.outline_item_id,
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


@router.post("/{novel_id}/chapters/{chapter_id}/revise", response_model=ChapterReviseOut)
async def revise_chapter(
    novel_id: int,
    chapter_id: int,
    body: ChapterReviseIn,
    session: AsyncSession = Depends(get_session),
):
    ch = await session.get(Chapter, chapter_id)
    if not ch or ch.novel_id != novel_id:
        raise HTTPException(404, "章节不存在")
    ver, task_id = await revise_and_commit(
        session, chapter_id, body.content, commit_to_knowledge=body.commit_to_knowledge
    )
    return ChapterReviseOut(
        id=ver.id,
        chapter_id=ver.chapter_id,
        version_type=ver.version_type,
        content=ver.content,
        consistency_report=ver.consistency_report,
        parent_version_id=ver.parent_version_id,
        created_at=ver.created_at,
        task_id=task_id,
    )


@router.post(
    "/{novel_id}/chapters/{chapter_id}/commit-knowledge",
    response_model=CommitKnowledgeOut,
)
async def commit_chapter_knowledge(
    novel_id: int,
    chapter_id: int,
    session: AsyncSession = Depends(get_session),
):
    """重试/仅重新入队知识库增量更新，不新建 user_edited 版本。"""
    ch = await session.get(Chapter, chapter_id)
    if not ch or ch.novel_id != novel_id:
        raise HTTPException(404, "章节不存在")
    try:
        task_id = await enqueue_revise_commit(session, chapter_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    latest = (
        await session.execute(
            select(ChapterVersion)
            .where(ChapterVersion.chapter_id == chapter_id)
            .order_by(ChapterVersion.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return CommitKnowledgeOut(
        chapter_id=chapter_id,
        task_id=task_id,
        version_id=latest.id if latest else None,
    )


@router.delete("/{novel_id}/chapters/{chapter_id}/versions/{version_id}")
async def remove_chapter_version(
    novel_id: int,
    chapter_id: int,
    version_id: int,
    session: AsyncSession = Depends(get_session),
):
    """删除单个章节版本。

    若删的是当前正文对应版本则回退到剩余最新版；删光最后一版则整章清除并回退大纲条目。
    """
    try:
        return await delete_chapter_version(session, novel_id, chapter_id, version_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.delete("/{novel_id}/chapters/{chapter_id}")
async def remove_chapter(
    novel_id: int,
    chapter_id: int,
    session: AsyncSession = Depends(get_session),
):
    """删除章节正文、版本链、摘要与向量；大纲条目保留并回退为 pending。

    Story Bible 增量抽取不回滚。
    """
    try:
        return await delete_chapter(session, novel_id, chapter_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
