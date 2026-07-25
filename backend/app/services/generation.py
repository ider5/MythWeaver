"""单章流式生成 + 递归记忆状态更新。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.client import get_llm_client
from app.llm.cost_tracker import log_cost
from app.llm.prompts import render
from app.models import Chapter, ChapterVersion, Novel, OutlineItem, RecurrentMemory
from app.services.consistency import run_critic_loop
from app.services.context_builder import build_context
from app.services.ingestion import incremental_update_chapter
from app.utils.chinese_text import count_chars
from app.utils.json_extract import extract_json

logger = logging.getLogger(__name__)


async def stream_generate_chapter(
    session: AsyncSession,
    novel_id: int,
    outline_item_id: int,
    *,
    run_critic: bool = True,
    max_critic_rounds: int = 2,
) -> AsyncIterator[dict[str, Any]]:
    """SSE 事件：delta / status / done / error。"""
    novel = await session.get(Novel, novel_id)
    if novel is None:
        yield {"event": "error", "message": "小说不存在"}
        return
    item = await session.get(OutlineItem, outline_item_id)
    if item is None:
        yield {"event": "error", "message": "大纲条目不存在"}
        return

    item.status = "generating"
    novel.status = "generating"
    await session.commit()

    yield {"event": "status", "message": "组装上下文…"}
    ctx = await build_context(session, novel, item)

    prompt = render(
        "generation.j2",
        genre=novel.genre or "玄幻",
        genre_hints=ctx.genre_hints,
        story_bible=ctx.story_bible or "（空）",
        memory=ctx.memory or "（空）",
        style_samples=ctx.style_samples or "（无）",
        summaries=ctx.summaries or "（无）",
        rag_context=ctx.rag_context or "（无）",
        recent_chapters=ctx.recent_chapters or "（无）",
        chapter_title=item.title,
        chapter_summary=item.summary,
        key_points=item.key_points or [],
    )

    yield {"event": "status", "message": "开始流式生成…", "context_tokens": ctx.total_tokens}
    client = get_llm_client()
    content = ""
    usage = {"input_tokens": 0, "output_tokens": 0, "provider": "", "model": ""}
    async for chunk in client.stream(
        [
            {"role": "system", "content": "你是专业网文作者，只输出章节正文。"},
            {"role": "user", "content": prompt},
        ],
        endpoint=client.generation_endpoint(),
    ):
        if "delta_text" in chunk:
            yield {"event": "delta", "text": chunk["delta_text"]}
        if chunk.get("done"):
            content = chunk.get("text") or content
            usage = {
                "input_tokens": chunk.get("input_tokens", 0),
                "output_tokens": chunk.get("output_tokens", 0),
                "provider": chunk.get("provider", ""),
                "model": chunk.get("model", ""),
            }

    await log_cost(
        session,
        purpose="generation",
        provider=usage["provider"],
        model=usage["model"],
        input_tokens=int(usage["input_tokens"]),
        output_tokens=int(usage["output_tokens"]),
        novel_id=novel_id,
    )

    # 创建章节与 generated 版本
    next_index = novel.chapter_count + 1
    chapter = Chapter(
        novel_id=novel_id,
        index=next_index,
        title=item.title or f"第{next_index}章",
        content=content,
        char_count=count_chars(content),
        status="raw",
        is_generated=True,
        outline_item_id=item.id,
    )
    session.add(chapter)
    await session.flush()
    ver = ChapterVersion(
        chapter_id=chapter.id,
        version_type="generated",
        content=content,
    )
    session.add(ver)
    await session.commit()
    await session.refresh(chapter)
    await session.refresh(ver)

    consistency_data = None
    if run_critic and max_critic_rounds >= 0:
        yield {"event": "status", "message": "一致性校验与 Critic…"}
        revised, report = await run_critic_loop(
            session,
            novel,
            content,
            recent_tail=ctx.recent_chapters,
            max_rounds=max_critic_rounds,
        )
        consistency_data = report.model_dump()
        if revised != content:
            content = revised
            chapter.content = content
            chapter.char_count = count_chars(content)
            critic_ver = ChapterVersion(
                chapter_id=chapter.id,
                version_type="critic_revised",
                content=content,
                consistency_report=consistency_data,
                parent_version_id=ver.id,
            )
            session.add(critic_ver)
            ver = critic_ver
            await session.commit()
            await session.refresh(ver)
        else:
            ver.consistency_report = consistency_data
            await session.commit()

    item.status = "done"
    novel.status = "ready"
    await session.commit()

    yield {
        "event": "done",
        "chapter_id": chapter.id,
        "version_id": ver.id,
        "content": content,
        "consistency": consistency_data,
    }


async def update_recurrent_memory(session: AsyncSession, novel_id: int, chapter: Chapter) -> None:
    client = get_llm_client()
    mem = (
        await session.execute(select(RecurrentMemory).where(RecurrentMemory.novel_id == novel_id))
    ).scalar_one_or_none()
    previous = ""
    if mem:
        previous = (
            f"{mem.ending_state}\n{mem.character_positions}\n"
            f"{mem.timeline_cursor}\n{mem.open_threads}"
        )
    prompt = render(
        "memory.j2",
        title=chapter.title,
        content=chapter.content[:8000],
        previous=previous or "（无）",
    )
    result = await client.chat(
        [{"role": "user", "content": prompt}],
        endpoint=client.summary_endpoint(),
        temperature=0.2,
        purpose="memory",
    )
    await log_cost(
        session,
        purpose="memory",
        provider=result.provider,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        novel_id=novel_id,
    )
    try:
        data = extract_json(result.text)
    except Exception:  # noqa: BLE001
        data = {
            "ending_state": chapter.content[-200:],
            "character_positions": {},
            "timeline_cursor": "",
            "open_threads": [],
        }
    if mem is None:
        mem = RecurrentMemory(novel_id=novel_id)
        session.add(mem)
    mem.last_chapter_index = chapter.index
    mem.ending_state = data.get("ending_state") or ""
    mem.character_positions = data.get("character_positions") or {}
    mem.timeline_cursor = data.get("timeline_cursor")
    mem.open_threads = data.get("open_threads") or []
    await session.commit()


async def revise_and_commit(
    session: AsyncSession,
    chapter_id: int,
    content: str,
    *,
    commit_to_knowledge: bool = True,
) -> ChapterVersion:
    chapter = await session.get(Chapter, chapter_id)
    if chapter is None:
        raise ValueError("章节不存在")
    # 找最新版本作为 parent
    versions = (
        await session.execute(
            select(ChapterVersion)
            .where(ChapterVersion.chapter_id == chapter_id)
            .order_by(ChapterVersion.id.desc())
        )
    ).scalars().all()
    parent_id = versions[0].id if versions else None
    chapter.content = content
    chapter.char_count = count_chars(content)
    ver = ChapterVersion(
        chapter_id=chapter_id,
        version_type="user_edited",
        content=content,
        parent_version_id=parent_id,
    )
    session.add(ver)
    await session.commit()
    await session.refresh(ver)

    if commit_to_knowledge:
        await incremental_update_chapter(session, chapter)
        await update_recurrent_memory(session, chapter.novel_id, chapter)
        novel = await session.get(Novel, chapter.novel_id)
        if novel and chapter.index > novel.chapter_count:
            novel.chapter_count = chapter.index
            await session.commit()
    return ver
