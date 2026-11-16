"""Story Bible 路由。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Chapter, Character, Novel, PlotThread, WorldSetting
from app.schemas.story_bible import (
    BibleProposalOut,
    CharacterCreate,
    CharacterOut,
    CharacterUpdate,
    PlotThreadCreate,
    PlotThreadOut,
    PlotThreadUpdate,
    StoryBibleOut,
    WorldSettingCreate,
    WorldSettingOut,
    WorldSettingUpdate,
    WritebackApplyIn,
    WritebackChangeOut,
    WritebackFieldOut,
    WritebackProposeIn,
)
from app.services import story_bible as bible_svc
from app.services import writeback as writeback_svc
from app.services.writeback import WritebackError

router = APIRouter(prefix="/api/novels/{novel_id}/bible", tags=["story_bible"])


async def _ensure_novel(session: AsyncSession, novel_id: int) -> Novel:
    novel = await session.get(Novel, novel_id)
    if not novel:
        raise HTTPException(404, "小说不存在")
    return novel


@router.get("", response_model=StoryBibleOut)
async def get_bible(novel_id: int, session: AsyncSession = Depends(get_session)):
    await _ensure_novel(session, novel_id)
    data = await bible_svc.list_bible(session, novel_id)
    return StoryBibleOut(
        characters=data["characters"],
        world_settings=data["world_settings"],
        plot_threads=data["plot_threads"],
    )


@router.post("/characters", response_model=CharacterOut)
async def create_character(
    novel_id: int, body: CharacterCreate, session: AsyncSession = Depends(get_session)
):
    await _ensure_novel(session, novel_id)
    row = Character(novel_id=novel_id, **body.model_dump())
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


@router.patch("/characters/{char_id}", response_model=CharacterOut)
async def update_character(
    novel_id: int,
    char_id: int,
    body: CharacterUpdate,
    session: AsyncSession = Depends(get_session),
):
    row = await session.get(Character, char_id)
    if not row or row.novel_id != novel_id:
        raise HTTPException(404, "人物不存在")
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(row, k, v)
    await session.commit()
    await session.refresh(row)
    return row


@router.delete("/characters/{char_id}")
async def delete_character(novel_id: int, char_id: int, session: AsyncSession = Depends(get_session)):
    row = await session.get(Character, char_id)
    if not row or row.novel_id != novel_id:
        raise HTTPException(404, "人物不存在")
    await session.delete(row)
    await session.commit()
    return {"message": "ok"}


@router.post("/world-settings", response_model=WorldSettingOut)
async def create_world(
    novel_id: int, body: WorldSettingCreate, session: AsyncSession = Depends(get_session)
):
    await _ensure_novel(session, novel_id)
    row = WorldSetting(novel_id=novel_id, **body.model_dump())
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


@router.patch("/world-settings/{ws_id}", response_model=WorldSettingOut)
async def update_world(
    novel_id: int,
    ws_id: int,
    body: WorldSettingUpdate,
    session: AsyncSession = Depends(get_session),
):
    row = await session.get(WorldSetting, ws_id)
    if not row or row.novel_id != novel_id:
        raise HTTPException(404, "设定不存在")
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(row, k, v)
    await session.commit()
    await session.refresh(row)
    return row


@router.delete("/world-settings/{ws_id}")
async def delete_world(novel_id: int, ws_id: int, session: AsyncSession = Depends(get_session)):
    row = await session.get(WorldSetting, ws_id)
    if not row or row.novel_id != novel_id:
        raise HTTPException(404, "设定不存在")
    await session.delete(row)
    await session.commit()
    return {"message": "ok"}


@router.post("/plot-threads", response_model=PlotThreadOut)
async def create_thread(
    novel_id: int, body: PlotThreadCreate, session: AsyncSession = Depends(get_session)
):
    await _ensure_novel(session, novel_id)
    row = PlotThread(novel_id=novel_id, **body.model_dump())
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


@router.patch("/plot-threads/{pt_id}", response_model=PlotThreadOut)
async def update_thread(
    novel_id: int,
    pt_id: int,
    body: PlotThreadUpdate,
    session: AsyncSession = Depends(get_session),
):
    row = await session.get(PlotThread, pt_id)
    if not row or row.novel_id != novel_id:
        raise HTTPException(404, "剧情线不存在")
    # 章节字段允许显式 null，用来清掉出现/回收章；其它字段的 null 仍表示「不改」。
    clearable = {"introduced_chapter", "resolved_chapter"}
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is None and k not in clearable:
            continue
        setattr(row, k, v)
    await session.commit()
    await session.refresh(row)
    return row


@router.delete("/plot-threads/{pt_id}")
async def delete_thread(novel_id: int, pt_id: int, session: AsyncSession = Depends(get_session)):
    row = await session.get(PlotThread, pt_id)
    if not row or row.novel_id != novel_id:
        raise HTTPException(404, "剧情线不存在")
    await session.delete(row)
    await session.commit()
    return {"message": "ok"}


def _raise_writeback(exc: WritebackError) -> None:
    raise HTTPException(exc.status_code, exc.detail) from exc


async def _proposal_out(session: AsyncSession, row) -> BibleProposalOut:
    title = None
    if row.chapter_id:
        chapter = await session.get(Chapter, row.chapter_id)
        if chapter is not None:
            title = chapter.title
    changes = []
    for raw in row.changes or []:
        changes.append(
            WritebackChangeOut(
                id=raw["id"],
                kind=raw["kind"],
                op=raw["op"],
                target_id=raw.get("target_id"),
                label=raw.get("label") or "",
                summary=raw.get("summary") or "",
                fields=[WritebackFieldOut(**field) for field in (raw.get("fields") or [])],
                after=raw.get("after") or {},
            )
        )
    return BibleProposalOut(
        id=row.id,
        novel_id=row.novel_id,
        chapter_id=row.chapter_id,
        chapter_index=row.chapter_index,
        chapter_title=title,
        status=row.status,
        changes=changes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/proposals", response_model=list[BibleProposalOut])
async def list_writeback_proposals(
    novel_id: int,
    status: str = Query("pending"),
    session: AsyncSession = Depends(get_session),
):
    await _ensure_novel(session, novel_id)
    try:
        rows = await writeback_svc.list_proposals(session, novel_id, status)
    except WritebackError as exc:
        _raise_writeback(exc)
    return [await _proposal_out(session, row) for row in rows]


@router.post("/proposals", response_model=BibleProposalOut)
async def propose_writeback(
    novel_id: int,
    body: WritebackProposeIn,
    session: AsyncSession = Depends(get_session),
):
    novel = await _ensure_novel(session, novel_id)
    chapter = await session.get(Chapter, body.chapter_id)
    if chapter is None or chapter.novel_id != novel_id:
        raise HTTPException(404, "章节不存在")
    try:
        row = await writeback_svc.ensure_generated_writeback(
            session, novel, chapter, force=body.force
        )
    except WritebackError as exc:
        await session.rollback()
        _raise_writeback(exc)
    await session.commit()
    await session.refresh(row)
    return await _proposal_out(session, row)


@router.post("/proposals/{proposal_id}/apply", response_model=BibleProposalOut)
async def apply_writeback(
    novel_id: int,
    proposal_id: int,
    body: WritebackApplyIn,
    session: AsyncSession = Depends(get_session),
):
    await _ensure_novel(session, novel_id)
    try:
        row = await writeback_svc.apply_proposal(session, novel_id, proposal_id, body.change_ids)
    except WritebackError as exc:
        await session.rollback()
        _raise_writeback(exc)
    await session.commit()
    await session.refresh(row)
    return await _proposal_out(session, row)


@router.post("/proposals/{proposal_id}/dismiss", response_model=BibleProposalOut)
async def dismiss_writeback(
    novel_id: int,
    proposal_id: int,
    session: AsyncSession = Depends(get_session),
):
    await _ensure_novel(session, novel_id)
    try:
        row = await writeback_svc.dismiss_proposal(session, novel_id, proposal_id)
    except WritebackError as exc:
        await session.rollback()
        _raise_writeback(exc)
    await session.commit()
    await session.refresh(row)
    return await _proposal_out(session, row)
