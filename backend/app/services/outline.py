"""大纲生成 / 编辑 / 确认。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.llm.client import get_llm_client
from app.llm.cost_tracker import log_cost
from app.llm.prompts import render
from app.services.writing_skills import stage_skill_text
from app.models import AsyncTask, Chapter, Novel, Outline, OutlineItem, RecurrentMemory, Summary
from app.services import story_bible as bible_svc
from app.services.scratch import is_scratch_origin
from app.utils.chinese_text import int_to_chinese
from app.utils.json_extract import extract_json

if TYPE_CHECKING:
    from app.services.tasks import TaskProgress

_CHAPTER_TITLE_PREFIX = re.compile(
    r"^[\s　]*第[零〇一二三四五六七八九十百千万两0-9]+章\s*[：:\-—–]?\s*"
)
_NAME_SPLIT = re.compile(r"[；;、,，\n/|]+")

# 模型可能用 Pagekin 驼峰或中文键；入库一律用这些规范名。
_BLUEPRINT_ALIASES: dict[str, tuple[str, ...]] = {
    "purpose": ("purpose", "goal", "chapter_goal", "主角小目标", "目标"),
    "conflict": ("conflict", "turning_point", "key_events", "keyEvents", "冲突与转折", "冲突"),
    "suspense_hook": ("suspense_hook", "suspenseHook", "hook", "suspense", "悬念钩子", "悬念"),
    "characters": ("characters", "cast", "appearing_characters", "appearingCharacters", "出场人物"),
}


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "；".join(str(v).strip() for v in value if str(v).strip())
    return str(value).strip()


def _as_name_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = _NAME_SPLIT.split(value)
    elif isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("name") or item.get("title") or ""))
            else:
                parts.append(str(item))
    else:
        parts = [str(value)]
    names: list[str] = []
    for part in parts:
        name = part.strip()
        if name and name not in names:
            names.append(name)
    return names


def _first_present(raw: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in raw and raw[key] is not None:
            return raw[key]
    return None


def blueprint_from_raw(raw: dict) -> dict[str, Any]:
    """取出蓝图字段。缺省为空，不改动 title / summary / key_points。"""
    return {
        "purpose": _as_text(_first_present(raw, _BLUEPRINT_ALIASES["purpose"])),
        "conflict": _as_text(_first_present(raw, _BLUEPRINT_ALIASES["conflict"])),
        "suspense_hook": _as_text(_first_present(raw, _BLUEPRINT_ALIASES["suspense_hook"])),
        "characters": _as_name_list(_first_present(raw, _BLUEPRINT_ALIASES["characters"])),
    }


def apply_blueprint(row: OutlineItem, raw: dict, *, fill_missing: bool) -> None:
    """写入蓝图。更新已有条目时，缺省或 null 保留原值。"""
    if fill_missing:
        fields = blueprint_from_raw(raw)
    else:
        fields = {}
        if "purpose" in raw and raw["purpose"] is not None:
            fields["purpose"] = _as_text(raw["purpose"])
        if "conflict" in raw and raw["conflict"] is not None:
            fields["conflict"] = _as_text(raw["conflict"])
        if "suspense_hook" in raw and raw["suspense_hook"] is not None:
            fields["suspense_hook"] = _as_text(raw["suspense_hook"])
        if "characters" in raw and raw["characters"] is not None:
            fields["characters"] = _as_name_list(raw["characters"])
    for key, value in fields.items():
        setattr(row, key, value)


def rewrite_outline_title(title: str, chapter_number: int) -> str:
    """按后端绝对章号重写标题前缀，不信任模型输出的章号。"""
    rest = _CHAPTER_TITLE_PREFIX.sub("", (title or "").strip()).strip()
    prefix = f"第{int_to_chinese(chapter_number)}章"
    if not rest:
        return prefix
    return f"{prefix}：{rest}"


def normalize_outline_items(
    items: list[dict],
    *,
    start_from_chapter: int,
) -> list[dict]:
    """将大纲条目校正为从 start_from_chapter 起连续编号。"""
    normalized: list[dict] = []
    for i, item in enumerate(items):
        chapter_number = start_from_chapter + i
        row = dict(item)
        row["order"] = i + 1
        row["title"] = rewrite_outline_title(str(item.get("title") or ""), chapter_number)
        row["summary"] = item.get("summary") or ""
        row["key_points"] = item.get("key_points") or []
        row.update(blueprint_from_raw(item))
        normalized.append(row)
    return normalized


async def _resolve_start_chapter(
    session: AsyncSession,
    novel: Novel,
    start_from_chapter: int | None,
) -> int:
    if start_from_chapter is not None:
        return start_from_chapter
    max_index = await session.scalar(
        select(func.max(Chapter.index)).where(Chapter.novel_id == novel.id)
    )
    base = max_index if max_index is not None else (novel.chapter_count or 0)
    return int(base) + 1


async def _progress(
    progress: TaskProgress | None,
    session: AsyncSession,
    *,
    pct: float,
    message: str,
) -> None:
    if progress is not None:
        await progress.update(session, progress=pct, message=message)


async def enqueue_outline_generate(
    session: AsyncSession,
    novel_id: int,
    *,
    chapter_count: int = 5,
    guidance: str | None = None,
    start_from_chapter: int | None = None,
) -> AsyncTask:
    """入队异步大纲生成，立即返回 task。"""
    from app.services.novel_role import is_reference_role
    from app.services.tasks import get_task_queue

    novel = await session.get(Novel, novel_id)
    if novel is None:
        raise ValueError("小说不存在")
    if is_reference_role(novel.role):
        raise ValueError("参考小说不能生成续写大纲")

    return await get_task_queue().enqueue(
        session,
        task_type="outline_generate",
        novel_id=novel_id,
        message="大纲生成排队中",
        result={
            "novel_id": novel_id,
            "chapter_count": chapter_count,
            "guidance": guidance,
            "start_from_chapter": start_from_chapter,
        },
    )


async def outline_generate_handler(session: AsyncSession, task: AsyncTask, progress: TaskProgress) -> dict:
    """异步：准备上下文 → LLM → 解析校正 → 落库。"""
    payload: dict[str, Any] = dict(task.result or {})
    novel_id = payload.get("novel_id") or task.novel_id
    if not novel_id:
        raise ValueError("缺少 novel_id")
    chapter_count = int(payload.get("chapter_count") or 5)
    guidance = payload.get("guidance")
    start_from = payload.get("start_from_chapter")
    start_from_chapter = int(start_from) if start_from is not None else None

    outline = await generate_outline(
        session,
        int(novel_id),
        chapter_count=chapter_count,
        guidance=guidance,
        start_from_chapter=start_from_chapter,
        progress=progress,
    )
    return {"ok": True, "outline_id": outline.id, "novel_id": outline.novel_id}


async def generate_outline(
    session: AsyncSession,
    novel_id: int,
    *,
    chapter_count: int = 5,
    guidance: str | None = None,
    start_from_chapter: int | None = None,
    progress: TaskProgress | None = None,
) -> Outline:
    novel = await session.get(Novel, novel_id)
    if novel is None:
        raise ValueError("小说不存在")

    start = await _resolve_start_chapter(session, novel, start_from_chapter)
    existing_count = max(start - 1, 0)
    # 进度走独立短事务；先取出标量，避免对象在 commit 后过期
    genre = novel.genre or "玄幻"
    premise = (novel.premise or "").strip()
    writing_style = (novel.writing_style or "").strip()
    scratch = is_scratch_origin(novel.origin)

    await _progress(progress, session, pct=8.0, message="准备上下文…")

    summaries = (
        await session.execute(
            select(Summary)
            .where(Summary.novel_id == novel_id, Summary.level == "chapter")
            .order_by(Summary.id.desc())
            .limit(8)
        )
    ).scalars().all()
    recent = "\n".join(f"- {s.content}" for s in reversed(list(summaries)))

    bible = await bible_svc.list_bible(session, novel_id)
    bible_text = bible_svc.format_bible_text(
        bible["characters"], bible["world_settings"], bible["plot_threads"]
    )
    mem = (
        await session.execute(select(RecurrentMemory).where(RecurrentMemory.novel_id == novel_id))
    ).scalar_one_or_none()
    memory = mem.ending_state if mem else "（尚无）"

    prompt = render(
        "outline.j2",
        chapter_count=chapter_count,
        genre=genre,
        guidance=guidance or "",
        premise=premise,
        writing_style=writing_style,
        is_scratch=scratch,
        recent_summaries=recent or "（无摘要）",
        story_bible=bible_text or "（空）",
        memory=memory,
        start_from_chapter=start,
        start_from_chinese=int_to_chinese(start),
        existing_chapter_count=existing_count,
        stage_skills=await stage_skill_text(session, "outline"),
    )

    # LLM 期间不得持有未提交写锁，否则进度独立连接 UPDATE 会死锁/locked
    await session.commit()
    await _progress(progress, session, pct=18.0, message="正在生成大纲…")
    client = get_llm_client()
    result = await client.chat(
        [{"role": "user", "content": prompt}],
        endpoint=client.generation_endpoint(),
        temperature=0.7,
        purpose="outline",
    )
    await log_cost(
        session,
        purpose="outline",
        provider=result.provider,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        novel_id=novel_id,
    )
    # log_cost 会 flush 占用写锁；先提交再推进度，避免 database is locked
    await session.commit()

    await _progress(progress, session, pct=72.0, message="解析并校正章号…")
    try:
        data = extract_json(result.text)
    except Exception:  # noqa: BLE001
        data = {
            "title": "续写大纲",
            "items": [
                {
                    "order": i + 1,
                    "title": f"第{int_to_chinese(start + i)}章",
                    "summary": f"待规划情节 {i + 1}",
                    "key_points": [],
                }
                for i in range(chapter_count)
            ],
        }

    raw_items = list(data.get("items") or [])
    # 条数不足时补齐，过多则截断，保证与规划章数一致
    while len(raw_items) < chapter_count:
        raw_items.append(
            {
                "order": len(raw_items) + 1,
                "title": "",
                "summary": f"待规划情节 {len(raw_items) + 1}",
                "key_points": [],
            }
        )
    raw_items = raw_items[:chapter_count]
    items = normalize_outline_items(raw_items, start_from_chapter=start)

    await _progress(progress, session, pct=88.0, message="保存大纲…")
    outline = Outline(
        novel_id=novel_id,
        title=data.get("title") or "续写大纲",
        status="draft",
        start_from_chapter=start,
    )
    session.add(outline)
    await session.flush()
    for item in items:
        session.add(
            OutlineItem(
                outline_id=outline.id,
                order=int(item["order"]),
                title=item["title"],
                summary=item.get("summary") or "",
                key_points=item.get("key_points") or [],
                purpose=item.get("purpose") or "",
                conflict=item.get("conflict") or "",
                suspense_hook=item.get("suspense_hook") or "",
                characters=item.get("characters") or [],
                status="pending",
            )
        )
    await session.commit()
    await _progress(progress, session, pct=98.0, message="即将完成…")
    return await get_outline(session, outline.id)


async def get_outline(session: AsyncSession, outline_id: int) -> Outline:
    result = await session.execute(
        select(Outline)
        .where(Outline.id == outline_id)
        .options(selectinload(Outline.items))
    )
    outline = result.scalar_one_or_none()
    if outline is None:
        raise ValueError("大纲不存在")
    return outline


async def list_outlines(session: AsyncSession, novel_id: int) -> list[Outline]:
    result = await session.execute(
        select(Outline)
        .where(Outline.novel_id == novel_id)
        .options(selectinload(Outline.items))
        .order_by(Outline.id.desc())
    )
    return list(result.scalars().all())


async def update_outline(
    session: AsyncSession,
    outline_id: int,
    *,
    title: str | None = None,
    items: list[dict] | None = None,
) -> Outline:
    outline = await get_outline(session, outline_id)
    if title is not None:
        outline.title = title
    if items is not None:
        existing = {it.id: it for it in list(outline.items)}
        keep: set[int] = set()
        for raw in items:
            item_id = raw.get("id")
            if item_id and item_id in existing:
                row = existing[item_id]
                row.order = int(raw["order"])
                row.title = raw.get("title") or ""
                row.summary = raw.get("summary") or ""
                row.key_points = raw.get("key_points") or []
                if raw.get("status"):
                    row.status = raw["status"]
                apply_blueprint(row, raw, fill_missing=False)
                keep.add(item_id)
            else:
                created = OutlineItem(
                    outline_id=outline.id,
                    order=int(raw["order"]),
                    title=raw.get("title") or "",
                    summary=raw.get("summary") or "",
                    key_points=raw.get("key_points") or [],
                    status=raw.get("status") or "pending",
                )
                apply_blueprint(created, raw, fill_missing=True)
                session.add(created)
        for oid, row in existing.items():
            if oid not in keep:
                await session.delete(row)
    await session.commit()
    return await get_outline(session, outline_id)


async def confirm_outline(session: AsyncSession, outline_id: int) -> Outline:
    outline = await get_outline(session, outline_id)
    outline.status = "confirmed"
    await session.commit()
    return await get_outline(session, outline_id)


async def delete_outline(session: AsyncSession, outline_id: int) -> dict:
    """删除大纲及其条目。

    策略：draft / confirmed 均可删。关联章节正文保留，
    Chapter.outline_item_id 经 FK ondelete=SET NULL 自动解绑。
    """
    outline = await get_outline(session, outline_id)
    item_ids = [i.id for i in outline.items]
    unbound = 0
    if item_ids:
        unbound = int(
            await session.scalar(
                select(func.count())
                .select_from(Chapter)
                .where(Chapter.outline_item_id.in_(item_ids))
            )
            or 0
        )
    novel_id = outline.novel_id
    oid = outline.id
    await session.delete(outline)
    await session.commit()
    return {
        "message": "大纲已删除",
        "outline_id": oid,
        "novel_id": novel_id,
        "unbound_chapters": unbound,
    }
