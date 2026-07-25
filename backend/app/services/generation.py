"""单章流式生成 + 递归记忆状态更新。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.client import get_llm_client
from app.llm.cost_tracker import log_cost
from app.llm.prompts import render
from app.models import Chapter, ChapterVersion, Novel, Outline, OutlineItem, RecurrentMemory, Summary
from app.services.consistency import run_critic_loop
from app.services.context_builder import build_context
from app.services.ingestion import incremental_update_chapter
from app.services.retrieval import delete_chapter_embedding
from app.utils.chinese_text import count_chars
from app.utils.json_extract import extract_json

logger = logging.getLogger(__name__)


def resolve_target_chapter_index(*, start_from_chapter: int, order: int) -> int:
    """大纲条目对应的绝对章号：start_from_chapter + order - 1。"""
    return int(start_from_chapter) + int(order) - 1


async def _resolve_generation_index(
    session: AsyncSession,
    novel: Novel,
    item: OutlineItem,
) -> int:
    """优先用大纲条目目标章号；缺大纲时回退到 max(已有 index, chapter_count)+1。"""
    outline = await session.get(Outline, item.outline_id)
    if outline is not None:
        return resolve_target_chapter_index(
            start_from_chapter=outline.start_from_chapter,
            order=item.order,
        )
    max_index = await session.scalar(
        select(func.max(Chapter.index)).where(Chapter.novel_id == novel.id)
    )
    base = max(int(max_index or 0), int(novel.chapter_count or 0))
    return base + 1


async def _upsert_generated_chapter(
    session: AsyncSession,
    *,
    novel_id: int,
    index: int,
    title: str,
    content: str,
    outline_item_id: int,
) -> tuple[Chapter, ChapterVersion, bool]:
    """按 (novel_id, index) 更新已有章或插入新章，并追加 generated 版本。

    返回 (chapter, version, overwritten)。
    """
    existing = (
        await session.execute(
            select(Chapter).where(Chapter.novel_id == novel_id, Chapter.index == index)
        )
    ).scalar_one_or_none()

    overwritten = existing is not None
    if existing is not None:
        chapter = existing
        chapter.title = title
        chapter.content = content
        chapter.char_count = count_chars(content)
        chapter.status = "raw"
        chapter.is_generated = True
        chapter.outline_item_id = outline_item_id
    else:
        chapter = Chapter(
            novel_id=novel_id,
            index=index,
            title=title,
            content=content,
            char_count=count_chars(content),
            status="raw",
            is_generated=True,
            outline_item_id=outline_item_id,
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
    return chapter, ver, overwritten


async def _reset_generating_status(
    session: AsyncSession,
    novel: Novel | None,
    item: OutlineItem | None,
) -> None:
    """生成失败时恢复状态，便于用户重试。"""
    try:
        if item is not None and item.status == "generating":
            item.status = "pending"
        if novel is not None and novel.status == "generating":
            novel.status = "ready"
        await session.commit()
    except Exception:  # noqa: BLE001
        logger.exception("重置 generating 状态失败")
        await session.rollback()


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

    try:
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

        if not (content or "").strip():
            raise RuntimeError("模型未返回正文（流式结果为空）")

        await log_cost(
            session,
            purpose="generation",
            provider=usage["provider"],
            model=usage["model"],
            input_tokens=int(usage["input_tokens"]),
            output_tokens=int(usage["output_tokens"]),
            novel_id=novel_id,
        )

        # 按大纲目标章号 upsert，避免 (novel_id, index) UNIQUE 冲突
        next_index = await _resolve_generation_index(session, novel, item)
        chapter, ver, overwritten = await _upsert_generated_chapter(
            session,
            novel_id=novel_id,
            index=next_index,
            title=item.title or f"第{next_index}章",
            content=content,
            outline_item_id=item.id,
        )
        if overwritten:
            yield {"event": "status", "message": "章节已存在，已覆盖生成"}

        consistency_data = None
        if run_critic and max_critic_rounds >= 0:
            yield {"event": "status", "message": "一致性校验与 Critic…"}
            revised, report, initial = await run_critic_loop(
                session,
                novel,
                content,
                recent_tail=ctx.recent_chapters,
                max_rounds=max_critic_rounds,
            )
            consistency_data = report.model_dump()
            if revised != content:
                # 草稿版保留初检；终检绑到 critic_revised（与正文一致）
                ver.consistency_report = initial.model_dump()
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
                # 未改写：报告直接写在本次 generated（含覆盖生成的最新版）
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
            "overwritten": overwritten,
            "chapter_index": next_index,
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("stream_generate_chapter failed novel=%s item=%s", novel_id, outline_item_id)
        await _reset_generating_status(session, novel, item)
        yield {"event": "error", "message": f"生成失败: {exc}"}


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


async def delete_chapter(session: AsyncSession, novel_id: int, chapter_id: int) -> dict:
    """删除章节正文及其版本链、摘要、向量。

    - 保留大纲条目，并将关联 OutlineItem.status 回退为 pending
    - Story Bible / 人物关系等增量抽取难以精确回滚，此处不动
    - 重算 novel.chapter_count / total_chars
    """
    chapter = await session.get(Chapter, chapter_id)
    if chapter is None or chapter.novel_id != novel_id:
        raise ValueError("章节不存在")

    outline_item_id = chapter.outline_item_id
    char_count = chapter.char_count or 0
    chapter_index = chapter.index

    # 显式清摘要（FK CASCADE 也会删，这里保证立即生效）
    summaries = (
        await session.execute(select(Summary).where(Summary.chapter_id == chapter_id))
    ).scalars().all()
    for s in summaries:
        await session.delete(s)

    await delete_chapter_embedding(session, chapter_id)
    await session.delete(chapter)
    await session.flush()

    outline_item_reset = False
    if outline_item_id is not None:
        item = await session.get(OutlineItem, outline_item_id)
        if item is not None and item.status in ("done", "generating"):
            item.status = "pending"
            outline_item_reset = True

    novel = await session.get(Novel, novel_id)
    if novel is not None:
        max_index = await session.scalar(
            select(func.max(Chapter.index)).where(Chapter.novel_id == novel_id)
        )
        novel.chapter_count = int(max_index) if max_index is not None else 0
        novel.total_chars = max(0, (novel.total_chars or 0) - char_count)

    await session.commit()
    return {
        "message": "章节已删除",
        "chapter_id": chapter_id,
        "chapter_index": chapter_index,
        "outline_item_id": outline_item_id,
        "outline_item_reset": outline_item_reset,
    }


async def delete_chapter_version(
    session: AsyncSession,
    novel_id: int,
    chapter_id: int,
    version_id: int,
) -> dict:
    """删除单个 ChapterVersion。

    - 若删的是当前正文对应版本：章节 content 回退到剩余版本中最新一版
    - 若已无任何版本：整章删除（含摘要/向量，大纲条目回退 pending）
    - 仅删中间版本时不改章节正文，也不动大纲条目
    - 一致性报告随版本行删除
    """
    chapter = await session.get(Chapter, chapter_id)
    if chapter is None or chapter.novel_id != novel_id:
        raise ValueError("章节不存在")

    version = await session.get(ChapterVersion, version_id)
    if version is None or version.chapter_id != chapter_id:
        raise ValueError("版本不存在")

    versions = (
        await session.execute(
            select(ChapterVersion)
            .where(ChapterVersion.chapter_id == chapter_id)
            .order_by(ChapterVersion.id)
        )
    ).scalars().all()
    latest = versions[-1] if versions else None
    is_current_body = (
        version.content == (chapter.content or "")
        or (latest is not None and latest.id == version.id)
    )

    await session.delete(version)
    await session.flush()

    remaining = (
        await session.execute(
            select(ChapterVersion)
            .where(ChapterVersion.chapter_id == chapter_id)
            .order_by(ChapterVersion.id)
        )
    ).scalars().all()

    if not remaining:
        result = await delete_chapter(session, novel_id, chapter_id)
        return {
            "message": "已删除最后一版，章节已清除",
            "chapter_id": chapter_id,
            "version_id": version_id,
            "chapter_deleted": True,
            "content_rolled_back": False,
            "remaining_versions": 0,
            "outline_item_id": result.get("outline_item_id"),
            "outline_item_reset": result.get("outline_item_reset", False),
            "chapter_index": result.get("chapter_index"),
        }

    content_rolled_back = False
    if is_current_body:
        newest = remaining[-1]
        old_chars = chapter.char_count or 0
        new_chars = count_chars(newest.content)
        chapter.content = newest.content
        chapter.char_count = new_chars
        novel = await session.get(Novel, novel_id)
        if novel is not None:
            novel.total_chars = max(0, (novel.total_chars or 0) - old_chars + new_chars)
        content_rolled_back = True

    await session.commit()
    return {
        "message": "版本已删除" if not content_rolled_back else "版本已删除，正文已回退",
        "chapter_id": chapter_id,
        "version_id": version_id,
        "chapter_deleted": False,
        "content_rolled_back": content_rolled_back,
        "remaining_versions": len(remaining),
        "outline_item_id": chapter.outline_item_id,
        "outline_item_reset": False,
        "active_content": chapter.content if content_rolled_back else None,
    }


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
