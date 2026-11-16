"""阶段写法：预览后安装。只保存提示词。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import WritingSkill
from app.schemas.skills import (
    CatalogOut,
    SkillDeletedOut,
    SkillInstallIn,
    SkillInstalledOut,
    SkillOut,
    SkillPreviewOut,
    SkillSourceIn,
    SkillUpdateIn,
)
from app.services.writing_skills import (
    STAGE_LABELS,
    SkillConflict,
    SkillNotFound,
    SkillParseError,
    delete_skill,
    find_by_name,
    injected_ids,
    install_skill,
    list_skills,
    load_catalog,
    parse_skill,
    read_catalog_source,
    set_enabled,
)

router = APIRouter(prefix="/api/skills", tags=["skills"])


def _out(row: WritingSkill, injected: bool) -> SkillOut:
    return SkillOut(
        id=row.id,
        name=row.name,
        description=row.description,
        stage=row.stage,
        stage_label=STAGE_LABELS.get(row.stage, row.stage),
        body=row.body,
        enabled=row.enabled,
        injected=injected,
        origin=row.origin,
        catalog_id=row.catalog_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _resolve(body: SkillSourceIn) -> tuple[str, str | None]:
    if body.catalog_id and body.catalog_id.strip():
        catalog_id = body.catalog_id.strip()
        return read_catalog_source(catalog_id), catalog_id
    return body.source or "", None


@router.get("", response_model=list[SkillOut])
async def get_skills(session: AsyncSession = Depends(get_session)) -> list[SkillOut]:
    rows = await list_skills(session)
    live = injected_ids(rows)
    return [_out(row, row.id in live) for row in rows]


@router.get("/catalog", response_model=list[CatalogOut])
async def get_catalog(session: AsyncSession = Depends(get_session)) -> list[CatalogOut]:
    rows = await list_skills(session)
    installed_ids = {row.catalog_id for row in rows if row.catalog_id}
    installed_names = {row.name for row in rows}
    items: list[CatalogOut] = []
    for catalog_id, parsed in load_catalog():
        items.append(
            CatalogOut(
                catalog_id=catalog_id,
                name=parsed.name,
                description=parsed.description,
                stage=parsed.stage,
                stage_label=parsed.stage_label,
                installed=catalog_id in installed_ids or parsed.name in installed_names,
            )
        )
    return items


@router.post("/preview", response_model=SkillPreviewOut)
async def preview_skill(
    body: SkillSourceIn,
    session: AsyncSession = Depends(get_session),
) -> SkillPreviewOut:
    catalog_id = body.catalog_id.strip() if body.catalog_id else None
    try:
        source, catalog_id = _resolve(body)
        parsed = parse_skill(source)
    except SkillParseError as exc:
        return SkillPreviewOut(ok=False, errors=exc.errors, catalog_id=catalog_id)
    existing = await find_by_name(session, parsed.name)
    return SkillPreviewOut(
        ok=True,
        name=parsed.name,
        description=parsed.description,
        stage=parsed.stage,
        stage_label=parsed.stage_label,
        body=parsed.body,
        catalog_id=catalog_id,
        already_installed=existing is not None,
    )


@router.post("", response_model=SkillInstalledOut)
async def install(
    body: SkillInstallIn,
    session: AsyncSession = Depends(get_session),
) -> SkillInstalledOut:
    try:
        source, catalog_id = _resolve(body)
        parsed = parse_skill(source)
    except SkillParseError as exc:
        raise HTTPException(status_code=400, detail=exc.errors) from exc
    origin = "catalog" if catalog_id else "upload"
    try:
        row, warning = await install_skill(
            session,
            parsed,
            origin=origin,
            catalog_id=catalog_id,
            replace=body.replace,
        )
    except SkillConflict as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc
    live = injected_ids(await list_skills(session))
    base = _out(row, row.id in live)
    return SkillInstalledOut(**base.model_dump(), warning=warning)


@router.patch("/{skill_id}", response_model=SkillOut)
async def update_skill(
    skill_id: int,
    body: SkillUpdateIn,
    session: AsyncSession = Depends(get_session),
) -> SkillOut:
    try:
        row = await set_enabled(session, skill_id, body.enabled)
    except SkillNotFound as exc:
        raise HTTPException(status_code=404, detail="写法不存在") from exc
    except SkillConflict as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc
    live = injected_ids(await list_skills(session))
    return _out(row, row.id in live)


@router.delete("/{skill_id}", response_model=SkillDeletedOut)
async def remove_skill(
    skill_id: int,
    session: AsyncSession = Depends(get_session),
) -> SkillDeletedOut:
    try:
        await delete_skill(session, skill_id)
    except SkillNotFound as exc:
        raise HTTPException(status_code=404, detail="写法不存在") from exc
    return SkillDeletedOut(message="已删除", id=skill_id)
