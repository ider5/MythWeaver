"""大纲生成 / 编辑 / 确认。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.llm.client import get_llm_client
from app.llm.cost_tracker import log_cost
from app.llm.prompts import render
from app.models import Novel, Outline, OutlineItem, RecurrentMemory, Summary
from app.services import story_bible as bible_svc
from app.utils.json_extract import extract_json


async def generate_outline(
    session: AsyncSession,
    novel_id: int,
    *,
    chapter_count: int = 5,
    guidance: str | None = None,
    start_from_chapter: int | None = None,
) -> Outline:
    novel = await session.get(Novel, novel_id)
    if novel is None:
        raise ValueError("小说不存在")

    start = start_from_chapter or (novel.chapter_count + 1)

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
        genre=novel.genre or "玄幻",
        guidance=guidance or "",
        recent_summaries=recent or "（无摘要）",
        story_bible=bible_text or "（空）",
        memory=memory,
    )
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
    try:
        data = extract_json(result.text)
    except Exception:  # noqa: BLE001
        data = {
            "title": "续写大纲",
            "items": [
                {
                    "order": i + 1,
                    "title": f"第{start + i}章",
                    "summary": f"待规划情节 {i + 1}",
                    "key_points": [],
                }
                for i in range(chapter_count)
            ],
        }

    outline = Outline(
        novel_id=novel_id,
        title=data.get("title") or "续写大纲",
        status="draft",
        start_from_chapter=start,
    )
    session.add(outline)
    await session.flush()
    for item in data.get("items") or []:
        session.add(
            OutlineItem(
                outline_id=outline.id,
                order=int(item.get("order") or 0),
                title=item.get("title") or "",
                summary=item.get("summary") or "",
                key_points=item.get("key_points") or [],
                status="pending",
            )
        )
    await session.commit()
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
        for old in list(outline.items):
            await session.delete(old)
        await session.flush()
        for item in items:
            session.add(
                OutlineItem(
                    outline_id=outline.id,
                    order=int(item["order"]),
                    title=item.get("title") or "",
                    summary=item.get("summary") or "",
                    key_points=item.get("key_points") or [],
                    status=item.get("status") or "pending",
                )
            )
    await session.commit()
    return await get_outline(session, outline_id)


async def confirm_outline(session: AsyncSession, outline_id: int) -> Outline:
    outline = await get_outline(session, outline_id)
    outline.status = "confirmed"
    await session.commit()
    return await get_outline(session, outline_id)
