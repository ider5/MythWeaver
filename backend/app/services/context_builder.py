"""上下文组装：约 16K token 预算，按优先级裁剪。"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Chapter, Novel, OutlineItem, RecurrentMemory, StyleSample, Summary
from app.services import story_bible as bible_svc
from app.services.chapter_length import take_text_tail
from app.services.retrieval import hybrid_search
from app.utils.chinese_text import count_tokens


@dataclass
class BuiltContext:
    recent_chapters: str = ""
    summaries: str = ""
    rag_context: str = ""
    story_bible: str = ""
    style_samples: str = ""
    memory: str = ""
    genre_hints: str = ""
    total_tokens: int = 0
    trimmed: list[str] = field(default_factory=list)


# 预算分配（约）
BUDGET = {
    "recent": 8000,
    "summaries": 2000,
    "rag": 1500,
    "bible": 2500,
    "style": 1500,
    "memory": 500,
}


def _chapter_block(ch, content: str, *, tail: bool) -> str:
    title = getattr(ch, "title", None) or ""
    label = f"### {title}（章尾）" if tail else f"### {title}"
    return f"{label}\n{content}"


def format_recent_chapters(chapters, *, budget_tokens: int) -> str:
    """最近章：能放下则用全文；超预算则优先保留上一章结尾，必要时再取再上一章结尾。"""
    recent = list(chapters[-2:] if chapters else [])
    if not recent:
        return ""

    def full(ch) -> str:
        return _chapter_block(ch, ch.content or "", tail=False)

    both = "\n\n".join(full(ch) for ch in recent)
    if len(both) <= budget_tokens * 2 and count_tokens(both) <= budget_tokens:
        return both

    last = recent[-1]
    last_full = full(last)
    last_full_tok = count_tokens(last_full) if len(last_full) <= budget_tokens * 2 else None

    if last_full_tok is not None and last_full_tok <= budget_tokens:
        if len(recent) == 1:
            return last_full
        remaining = budget_tokens - last_full_tok
        if remaining < 80:
            return last_full
        prev = recent[0]
        prev_tail = take_text_tail(prev.content or "", max(40, remaining - 50))
        combined = _chapter_block(prev, prev_tail, tail=True) + "\n\n" + last_full
        if count_tokens(combined) <= budget_tokens:
            return combined
        return last_full

    last_share = budget_tokens if len(recent) == 1 else max(200, int(budget_tokens * 0.65))
    last_tail = take_text_tail(last.content or "", max(80, last_share - 50))
    last_block = _chapter_block(last, last_tail, tail=True)
    if len(recent) == 1:
        return last_block
    remaining = budget_tokens - count_tokens(last_block)
    if remaining < 80:
        return last_block
    prev = recent[0]
    prev_tail = take_text_tail(prev.content or "", max(40, remaining - 50))
    combined = _chapter_block(prev, prev_tail, tail=True) + "\n\n" + last_block
    guard = 0
    while count_tokens(combined) > budget_tokens and remaining > 80 and guard < 8:
        remaining = max(40, int(remaining * 0.8))
        prev_tail = take_text_tail(prev.content or "", remaining)
        combined = _chapter_block(prev, prev_tail, tail=True) + "\n\n" + last_block
        guard += 1
    if count_tokens(combined) > budget_tokens:
        return last_block
    return combined


async def build_context(
    session: AsyncSession,
    novel: Novel,
    outline_item: OutlineItem,
    *,
    upto_chapter_index: int | None = None,
) -> BuiltContext:
    settings = get_settings()
    total_budget = settings.context_token_budget

    if upto_chapter_index is None:
        upto_chapter_index = novel.chapter_count

    chapters = (
        await session.execute(
            select(Chapter)
            .where(Chapter.novel_id == novel.id, Chapter.index <= upto_chapter_index)
            .order_by(Chapter.index)
        )
    ).scalars().all()

    # 最近 2 章：能放下则全文，超预算改用章尾（上一章结尾优先）
    recent = chapters[-2:] if chapters else []

    # 前 5 章章摘要 + 卷摘要
    chapter_summaries = (
        await session.execute(
            select(Summary)
            .where(Summary.novel_id == novel.id, Summary.level == "chapter")
            .order_by(Summary.id.desc())
            .limit(20)
        )
    ).scalars().all()
    # 取最近 5 个章摘要（按章节 index）
    ch_map = {c.id: c for c in chapters}
    chap_sum_sorted = sorted(
        [s for s in chapter_summaries if s.chapter_id in ch_map],
        key=lambda s: ch_map[s.chapter_id].index if s.chapter_id else 0,
        reverse=True,
    )[:5]
    vol_summaries = (
        await session.execute(
            select(Summary).where(Summary.novel_id == novel.id, Summary.level == "volume")
        )
    ).scalars().all()

    # RAG
    query = f"{outline_item.title}\n{outline_item.summary}\n" + "\n".join(outline_item.key_points or [])
    exclude = {c.id for c in recent}
    rag_hits = await hybrid_search(session, novel.id, query, top_k=8, exclude_chapter_ids=exclude)

    # Story Bible
    bible = await bible_svc.list_bible(session, novel.id)
    bible_text = bible_svc.format_bible_text(
        bible["characters"], bible["world_settings"], bible["plot_threads"]
    )

    # 文风样本
    samples = (
        await session.execute(
            select(StyleSample).where(StyleSample.novel_id == novel.id).limit(3)
        )
    ).scalars().all()
    if not samples and chapters:
        # 回退：取前几章片段
        style_text = "\n\n---\n\n".join((c.content or "")[:400] for c in chapters[:3])
    else:
        style_text = "\n\n---\n\n".join(s.content for s in samples)

    # 递归记忆
    mem = (
        await session.execute(select(RecurrentMemory).where(RecurrentMemory.novel_id == novel.id))
    ).scalar_one_or_none()
    memory_text = ""
    if mem:
        memory_text = (
            f"结尾状态：{mem.ending_state}\n"
            f"人物：{mem.character_positions}\n"
            f"时间线：{mem.timeline_cursor}\n"
            f"未解：{mem.open_threads}"
        )

    from app.llm.prompts import render

    genre_hints = render("genre_hints.j2", genre=novel.genre or "玄幻")

    # 组装可裁剪部分
    trimmed: list[str] = []
    vol_parts = [f"[{s.volume_key}] {s.content}" for s in vol_summaries]
    chap_parts = []
    for s in chap_sum_sorted:
        ch = ch_map.get(s.chapter_id)  # type: ignore[arg-type]
        title = ch.title if ch else ""
        chap_parts.append(f"- {title}: {s.content}")

    rag_n = len(rag_hits)
    chap_n = len(chap_parts)
    include_vol = True

    def assemble_summaries(use_vol: bool, n_chap: int) -> str:
        parts = []
        if use_vol and vol_parts:
            parts.append("卷摘要：\n" + "\n".join(vol_parts))
        if n_chap > 0:
            parts.append("章摘要：\n" + "\n".join(chap_parts[:n_chap]))
        return "\n\n".join(parts)

    def assemble_rag(n: int) -> str:
        lines = []
        for ch, score, snippet in rag_hits[:n]:
            lines.append(f"- [{ch.title}] (相关度{score:.2f}) {snippet}")
        return "\n".join(lines)

    summaries_text = assemble_summaries(include_vol, chap_n)
    rag_text = assemble_rag(rag_n)

    # Story Bible / 记忆优先占预算；recent 超预算则章尾切片
    bible_tokens = count_tokens(bible_text)
    memory_tokens = count_tokens(memory_text)
    min_flexible = 1500
    recent_budget = min(
        BUDGET["recent"],
        max(400, total_budget - bible_tokens - memory_tokens - min_flexible),
    )
    recent_text = format_recent_chapters(recent, budget_tokens=recent_budget)

    fixed = count_tokens(recent_text) + bible_tokens + memory_tokens
    flexible_budget = max(total_budget - fixed, 2000)

    style_use = style_text
    while True:
        used = (
            count_tokens(summaries_text)
            + count_tokens(rag_text)
            + count_tokens(style_use)
        )
        if used <= flexible_budget:
            break
        # 裁剪优先级：卷摘要 → RAG 条数 → 章摘要数量 → 文风
        if include_vol and vol_parts:
            include_vol = False
            summaries_text = assemble_summaries(False, chap_n)
            trimmed.append("volume_summaries")
            continue
        if rag_n > 3:
            rag_n -= 1
            rag_text = assemble_rag(rag_n)
            trimmed.append("rag")
            continue
        if chap_n > 2:
            chap_n -= 1
            summaries_text = assemble_summaries(include_vol, chap_n)
            trimmed.append("chapter_summaries")
            continue
        if count_tokens(style_use) > 400:
            style_use = style_use[: max(200, len(style_use) // 2)]
            trimmed.append("style")
            continue
        break

    ctx = BuiltContext(
        recent_chapters=recent_text,
        summaries=summaries_text,
        rag_context=rag_text,
        story_bible=bible_text,
        style_samples=style_use,
        memory=memory_text,
        genre_hints=genre_hints,
        trimmed=trimmed,
    )
    ctx.total_tokens = (
        count_tokens(recent_text)
        + count_tokens(summaries_text)
        + count_tokens(rag_text)
        + count_tokens(bible_text)
        + count_tokens(style_use)
        + count_tokens(memory_text)
        + count_tokens(genre_hints)
    )
    return ctx
