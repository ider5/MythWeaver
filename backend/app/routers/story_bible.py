"""Story Bible 路由。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Character, Novel, PlotThread, WorldSetting
from app.schemas.story_bible import (
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
)
from app.services import story_bible as bible_svc

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
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
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
