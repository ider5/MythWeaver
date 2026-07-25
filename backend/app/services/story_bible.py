"""Story Bible CRUD + 自动抽取合并。"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Character, PlotThread, WorldSetting


def _norm_name(name: str) -> str:
    return name.strip().replace(" ", "")


async def list_bible(session: AsyncSession, novel_id: int) -> dict[str, list]:
    chars = (
        await session.execute(select(Character).where(Character.novel_id == novel_id).order_by(Character.id))
    ).scalars().all()
    worlds = (
        await session.execute(
            select(WorldSetting).where(WorldSetting.novel_id == novel_id).order_by(WorldSetting.id)
        )
    ).scalars().all()
    threads = (
        await session.execute(
            select(PlotThread).where(PlotThread.novel_id == novel_id).order_by(PlotThread.id)
        )
    ).scalars().all()
    return {"characters": list(chars), "world_settings": list(worlds), "plot_threads": list(threads)}


async def merge_extraction(
    session: AsyncSession,
    novel_id: int,
    data: dict[str, Any],
    *,
    chapter_index: int | None = None,
) -> None:
    """合并 LLM 抽取结果到 Story Bible。"""
    for c in data.get("characters") or []:
        name = _norm_name(c.get("name") or "")
        if not name:
            continue
        existing = await _find_character(session, novel_id, name, c.get("aliases") or [])
        if existing is None:
            existing = Character(novel_id=novel_id, name=name, aliases=[])
            session.add(existing)
        aliases = list(existing.aliases or [])
        for a in c.get("aliases") or []:
            a = _norm_name(str(a))
            if a and a != name and a not in aliases:
                aliases.append(a)
        existing.aliases = aliases
        if c.get("role"):
            existing.role = c["role"]
        if c.get("status"):
            existing.status = c["status"]
        if c.get("personality"):
            existing.personality = c["personality"]
        if c.get("speech_style"):
            existing.speech_style = c["speech_style"]
        if chapter_index is not None:
            existing.last_appear_chapter = chapter_index

    for w in data.get("world_settings") or []:
        content = (w.get("content") or "").strip()
        if not content:
            continue
        title = (w.get("title") or content[:20]).strip()
        dup = await session.execute(
            select(WorldSetting).where(
                WorldSetting.novel_id == novel_id,
                WorldSetting.title == title,
            )
        )
        row = dup.scalar_one_or_none()
        if row is None:
            session.add(
                WorldSetting(
                    novel_id=novel_id,
                    category=w.get("category") or "规则",
                    title=title,
                    content=content,
                    do_not_violate=w.get("do_not_violate"),
                )
            )
        else:
            row.content = content
            if w.get("do_not_violate"):
                row.do_not_violate = w["do_not_violate"]
            if w.get("category"):
                row.category = w["category"]

    for t in data.get("plot_threads") or []:
        title = (t.get("title") or "").strip()
        if not title:
            continue
        dup = await session.execute(
            select(PlotThread).where(PlotThread.novel_id == novel_id, PlotThread.title == title)
        )
        row = dup.scalar_one_or_none()
        if row is None:
            session.add(
                PlotThread(
                    novel_id=novel_id,
                    title=title,
                    description=t.get("description"),
                    thread_type=t.get("thread_type") or "伏笔",
                    status=t.get("status") or "未回收",
                    introduced_chapter=chapter_index,
                )
            )
        else:
            if t.get("description"):
                row.description = t["description"]
            if t.get("status"):
                row.status = t["status"]

    await session.flush()


async def _find_character(
    session: AsyncSession, novel_id: int, name: str, aliases: list
) -> Optional[Character]:
    rows = (
        await session.execute(select(Character).where(Character.novel_id == novel_id))
    ).scalars().all()
    candidates = {_norm_name(name)} | {_norm_name(str(a)) for a in aliases if a}
    for row in rows:
        names = {_norm_name(row.name)} | {_norm_name(a) for a in (row.aliases or [])}
        if names & candidates:
            return row
    return None


def format_bible_text(
    characters: list[Character],
    world_settings: list[WorldSetting],
    plot_threads: list[PlotThread],
    *,
    max_chars: int = 4000,
) -> str:
    parts: list[str] = []
    if characters:
        parts.append("## 人物")
        for c in characters:
            alias = "、".join(c.aliases or [])
            line = f"- {c.name}"
            if alias:
                line += f"（别称：{alias}）"
            if c.role:
                line += f" [{c.role}]"
            if c.status:
                line += f" 状态：{c.status}"
            if c.personality:
                line += f" 性格：{c.personality}"
            if c.speech_style:
                line += f" 语言：{c.speech_style}"
            parts.append(line)
    if world_settings:
        parts.append("## 世界观")
        for w in world_settings:
            line = f"- [{w.category}] {w.title}: {w.content}"
            if w.do_not_violate:
                line += f" 【禁止】{w.do_not_violate}"
            parts.append(line)
    if plot_threads:
        parts.append("## 剧情线")
        for t in plot_threads:
            parts.append(f"- ({t.status}/{t.thread_type}) {t.title}: {t.description or ''}")
    text = "\n".join(parts)
    if len(text) > max_chars:
        return text[:max_chars] + "…"
    return text


def match_alias_mentions(content: str, characters: list[Character]) -> list[dict[str, str]]:
    """检查正文中出现的称谓是否都能映射到已知人物。启发式：返回可疑问题。"""
    issues: list[dict[str, str]] = []
    known: set[str] = set()
    for c in characters:
        known.add(c.name)
        known.update(c.aliases or [])
    # 简单启发：不做过度 NLP，留给 LLM Critic；此处仅检测明显空别称表场景
    if not known and len(content) > 500:
        issues.append(
            {
                "type": "alias",
                "severity": "info",
                "message": "Story Bible 尚无人物卡，无法做别称校验",
            }
        )
    return issues
