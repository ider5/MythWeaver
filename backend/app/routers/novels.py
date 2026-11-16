"""小说与章节路由。"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Chapter, ChapterVersion, Novel, OutlineItem
from app.schemas.generation import ConsistencyIssue, OpenThreadsOut, QualitySignals
from app.schemas.novel import (
    ChapterOut,
    ChapterPreview,
    ChapterReviseIn,
    ChapterReviseOut,
    ChapterVersionOut,
    CommitKnowledgeOut,
    CriticSelectReviseIn,
    CriticSelectReviseOut,
    ImportConfirmIn,
    ImportPreviewOut,
    NovelCreate,
    NovelOut,
    NovelUpdate,
    ScratchCreate,
    ScratchSeedOut,
)
from app.services import ingestion
from app.services import scratch as scratch_svc
from app.services.chapter_length import refresh_original_chapter_stats, resolve_target_chars
from app.services.epub_export import build_epub
from app.services.epub_import import EpubImportError
from app.services import novel_backup
from app.services.scratch import ScratchError, normalize_origin
from app.services.consistency import critic_revise_selected
from app.services.quality_loop import assess_chapter_quality, list_open_threads
from app.services.novel_role import (
    REFERENCE_EXPORT_DETAIL,
    is_reference_role,
    normalize_role,
)
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


async def _read_backup_upload(file: UploadFile) -> bytes:
    chunks: list[bytes] = []
    total = 0
    limit = novel_backup.MAX_ZIP_BYTES
    while True:
        block = await file.read(1024 * 1024)
        if not block:
            break
        total += len(block)
        if total > limit:
            raise HTTPException(413, f"备份包超过 {limit // (1024 * 1024)}MB")
        chunks.append(block)
    return b"".join(chunks)


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
async def list_novels(
    role: str | None = Query(default=None),
    origin: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
):
    """列出小说。`role=manuscript` 是续写默认来源；`reference` 不进入该列表。

    `origin=scratch` 只返回从零开书；`import` 只返回导入续写。
    """
    stmt = select(Novel).order_by(Novel.id.desc())
    if role is not None and role != "":
        try:
            role = normalize_role(role)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        stmt = stmt.where(Novel.role == role)
    if origin is not None and origin != "":
        try:
            origin = normalize_origin(origin)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        stmt = stmt.where(Novel.origin == origin)
    rows = (await session.execute(stmt)).scalars().all()
    return rows


@router.post("", response_model=NovelOut)
async def create_novel(body: NovelCreate, session: AsyncSession = Depends(get_session)):
    novel = Novel(**body.model_dump())
    session.add(novel)
    await session.commit()
    await session.refresh(novel)
    return novel


@router.post("/scratch", response_model=NovelOut)
async def create_scratch(body: ScratchCreate, session: AsyncSession = Depends(get_session)):
    """从零开书。不接收原稿，状态为 blank，直到播种设定。"""
    try:
        return await scratch_svc.create_scratch_novel(
            session,
            title=body.title,
            genre=body.genre,
            premise=body.premise,
            writing_style=body.writing_style,
            author=body.author,
        )
    except ScratchError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@router.post("/{novel_id}/scratch/seed", response_model=ScratchSeedOut)
async def seed_scratch(novel_id: int, session: AsyncSession = Depends(get_session)):
    """用已保存的前提播种 Story Bible。导入续写的书返回 409。"""
    try:
        return await scratch_svc.seed_scratch_bible(session, novel_id)
    except ScratchError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


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
    updates = body.model_dump(exclude_unset=True)
    # 用途只能在导入时选定；中途改 role 会绕过导出/续写护栏。
    if "role" in updates and updates["role"] != novel.role:
        raise HTTPException(400, "不能通过编辑修改用途；请新建原稿或参考书")
    updates.pop("role", None)
    for k, v in updates.items():
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


def _scoped_chapters(
    chapters: list[Chapter],
    *,
    volume: str | None,
    chapter_id: int | None,
) -> list[Chapter]:
    if volume is not None and chapter_id is not None:
        raise HTTPException(400, "请只选择一卷或一章")
    if chapter_id is not None:
        picked = [ch for ch in chapters if ch.id == chapter_id]
        if not picked:
            raise HTTPException(404, "章节不存在")
        return picked
    if volume is not None:
        key = volume.strip()
        if not key:
            raise HTTPException(400, "卷名不能为空")
        picked = [ch for ch in chapters if (ch.volume or "").strip() == key]
        if not picked:
            raise HTTPException(404, "这一卷没有章节")
        return picked
    return list(chapters)


def _export_stem(novel_title: str, chapters: list[Chapter], *, volume: str | None, chapter_id: int | None) -> str:
    base = (novel_title or "未命名").strip() or "未命名"
    if chapter_id is not None and chapters:
        label = (chapters[0].title or "").strip() or f"第{chapters[0].index}章"
        base = f"{base}-{label}"
    elif volume is not None and volume.strip():
        base = f"{base}-{volume.strip()}"
    return base[:120]


@router.get("/{novel_id}/export")
async def export_novel(
    novel_id: int,
    fmt: str = Query("txt", alias="format"),
    volume: str | None = Query(None),
    chapter_id: int | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    """导出当前章节正文。format=txt|md|epub；volume 与 chapter_id 只能二选一。"""
    fmt = (fmt or "txt").lower().strip()
    if fmt not in ("txt", "md", "epub"):
        raise HTTPException(400, "format 仅支持 txt、md 或 epub")

    novel = await session.get(Novel, novel_id)
    if not novel:
        raise HTTPException(404, "小说不存在")
    if is_reference_role(novel.role):
        raise HTTPException(409, REFERENCE_EXPORT_DETAIL)

    rows = (
        await session.execute(
            select(Chapter).where(Chapter.novel_id == novel_id).order_by(Chapter.index)
        )
    ).scalars().all()
    chapters = _scoped_chapters(list(rows), volume=volume, chapter_id=chapter_id)
    stem = _export_stem(novel.title, chapters, volume=volume, chapter_id=chapter_id)
    book_title = novel.title or "未命名"
    if chapter_id is not None and chapters:
        label = (chapters[0].title or "").strip() or f"第{chapters[0].index}章"
        book_title = f"{book_title} · {label}"
    elif volume is not None and volume.strip():
        book_title = f"{book_title} · {volume.strip()}"

    if fmt == "epub":
        payload = build_epub(
            title=book_title,
            author=getattr(novel, "author", None),
            chapters=[
                ((ch.title or "").strip() or f"第{ch.index}章", ch.content or "")
                for ch in chapters
            ],
        )
        filename = _safe_filename(stem, "epub")
        return Response(
            content=payload,
            media_type="application/epub+zip",
            headers={"Content-Disposition": _content_disposition(filename, "epub")},
        )

    body = _build_export_text(chapters, fmt)
    filename = _safe_filename(stem, fmt)
    media = "text/markdown; charset=utf-8" if fmt == "md" else "text/plain; charset=utf-8"
    return Response(
        content=body.encode("utf-8"),
        media_type=media,
        headers={"Content-Disposition": _content_disposition(filename, fmt)},
    )


@router.get("/{novel_id}/backup")
async def download_novel_backup(novel_id: int, session: AsyncSession = Depends(get_session)):
    """下载一本小说的数据行 ZIP。原稿和参考本都可以，不含任务与费用。"""
    try:
        payload, filename = await novel_backup.export_novel_zip(session, novel_id)
    except novel_backup.BackupError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": _content_disposition(filename, "zip")},
    )


@router.post("/backup/restore", response_model=NovelOut)
async def restore_novel_backup(
    file: UploadFile = File(...),
    title: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
):
    """从 ZIP 恢复为一本新小说，不覆盖原书。"""
    raw = await _read_backup_upload(file)
    try:
        novel = await novel_backup.restore_novel_zip(session, raw, title=title)
    except novel_backup.BackupError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    return novel


@router.post("/import/preview", response_model=ImportPreviewOut)
async def import_preview(
    file: UploadFile | None = File(None),
    files: list[UploadFile] | None = File(None),
    title: str = Form("未命名小说"),
):
    try:
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
        return ingestion.preview_from_upload(raw, filename=name, suggested_title=suggested)
    except EpubImportError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/import/confirm", response_model=NovelOut)
async def import_confirm(body: ImportConfirmIn, session: AsyncSession = Depends(get_session)):
    try:
        novel = await ingestion.confirm_import(
            session,
            import_token=body.import_token,
            title=body.title,
            author=body.author,
            genre=body.genre,
            role=body.role,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return novel


@router.post("/{novel_id}/ingest")
async def start_ingest(novel_id: int, session: AsyncSession = Depends(get_session)):
    from app.services.tasks import TaskDuplicateError

    try:
        task = await ingestion.start_ingestion(session, novel_id)
    except ScratchError as e:
        raise HTTPException(e.status_code, e.detail) from e
    except TaskDuplicateError as e:
        raise HTTPException(409, str(e)) from e
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


@router.get("/{novel_id}/open-threads", response_model=OpenThreadsOut)
async def open_threads(
    novel_id: int,
    chapter_index: int = Query(..., ge=1),
    session: AsyncSession = Depends(get_session),
):
    """写作台未回收伏笔。已回收、或尚未出场的线不返回。"""
    novel = await session.get(Novel, novel_id)
    if novel is None:
        raise HTTPException(404, "小说不存在")
    return await list_open_threads(session, novel_id, chapter_index)


@router.get("/{novel_id}/chapters/{chapter_id}/quality", response_model=QualitySignals)
async def chapter_quality(
    novel_id: int,
    chapter_id: int,
    session: AsyncSession = Depends(get_session),
):
    """对照文风样本、计划回收章、篇幅和章末钩子。不调用模型。"""
    chapter = await session.get(Chapter, chapter_id)
    if chapter is None or chapter.novel_id != novel_id:
        raise HTTPException(404, "章节不存在")
    novel = await session.get(Novel, novel_id)
    if novel is None:
        raise HTTPException(404, "小说不存在")
    hook = ""
    if chapter.outline_item_id:
        item = await session.get(OutlineItem, chapter.outline_item_id)
        if item is not None:
            hook = item.suspense_hook or ""
    target = await resolve_target_chars(session, novel, None)
    return await assess_chapter_quality(
        session,
        novel_id,
        chapter.content or "",
        chapter_index=chapter.index,
        target_chars=target,
        suspense_hook=hook,
        include_local_rules=True,
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
    "/{novel_id}/chapters/{chapter_id}/critic-select-revise",
    response_model=CriticSelectReviseOut,
)
async def critic_select_revise(
    novel_id: int,
    chapter_id: int,
    body: CriticSelectReviseIn,
    session: AsyncSession = Depends(get_session),
):
    """按勾选问题修稿：默认仅预览；confirm=true 时写入版本（可选入库）。"""
    ch = await session.get(Chapter, chapter_id)
    if not ch or ch.novel_id != novel_id:
        raise HTTPException(404, "章节不存在")
    novel = await session.get(Novel, novel_id)
    if novel is None:
        raise HTTPException(404, "小说不存在")

    issues = [
        ConsistencyIssue(
            type=i.type,
            severity=i.severity,
            message=i.message,
            detail=i.detail,
        )
        for i in body.issues
    ]
    base = body.content
    revised, report = await critic_revise_selected(session, novel, base, issues)
    changed = revised.strip() != base.strip()
    version_id = None
    task_id = None
    if body.confirm and changed:
        ver, task_id = await revise_and_commit(
            session,
            chapter_id,
            revised,
            commit_to_knowledge=body.commit_to_knowledge,
        )
        version_id = ver.id
        if ver.consistency_report is None:
            ver.consistency_report = report.model_dump()
            await session.commit()
    return CriticSelectReviseOut(
        base_content=base,
        revised_content=revised,
        consistency=report.model_dump(),
        changed=changed,
        version_id=version_id,
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
    from app.services.tasks import TaskDuplicateError

    try:
        task_id = await enqueue_revise_commit(session, chapter_id)
    except TaskDuplicateError as exc:
        raise HTTPException(409, str(exc)) from exc
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
