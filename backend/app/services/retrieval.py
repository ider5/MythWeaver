"""向量检索 + 关键词混合检索。"""

from __future__ import annotations

import logging
import math
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.llm.client import get_llm_client
from app.llm.cost_tracker import log_cost
from app.models import Chapter, Summary
from app.utils.chinese_text import extract_keywords

logger = logging.getLogger(__name__)


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def upsert_chapter_embedding(
    session: AsyncSession,
    chapter: Chapter,
    vector: list[float],
) -> None:
    chapter.embedding_json = vector
    settings = get_settings()
    try:
        # 先删后插
        await session.execute(
            text("DELETE FROM chapter_embeddings WHERE chapter_id = :cid"),
            {"cid": chapter.id},
        )
        # sqlite-vec 插入格式
        await session.execute(
            text(
                "INSERT INTO chapter_embeddings(chapter_id, embedding) VALUES (:cid, :emb)"
            ),
            {"cid": chapter.id, "emb": _serialize_vec(vector)},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("vec upsert 回退到 JSON: %s", exc)
    await session.flush()


def _serialize_vec(vector: list[float]) -> bytes:
    """sqlite-vec 接受 float blob；若失败上层已有 JSON 回退。"""
    import struct

    return struct.pack(f"{len(vector)}f", *vector)


async def embed_and_store(
    session: AsyncSession,
    chapter: Chapter,
    text_content: str,
    *,
    novel_id: int,
) -> None:
    client = get_llm_client()
    vectors, tokens = await client.embed([text_content[:6000]])
    if not vectors:
        return
    await upsert_chapter_embedding(session, chapter, vectors[0])
    await log_cost(
        session,
        purpose="embed",
        provider="openai",
        model=get_settings().embedding_model,
        input_tokens=tokens,
        novel_id=novel_id,
    )


async def hybrid_search(
    session: AsyncSession,
    novel_id: int,
    query: str,
    *,
    top_k: int = 8,
    exclude_chapter_ids: Optional[set[int]] = None,
) -> list[tuple[Chapter, float, str]]:
    """返回 [(chapter, score, snippet)]。"""
    exclude_chapter_ids = exclude_chapter_ids or set()
    client = get_llm_client()
    try:
        vectors, tokens = await client.embed([query])
        await log_cost(
            session,
            purpose="embed",
            provider="openai",
            model=get_settings().embedding_model,
            input_tokens=tokens,
            novel_id=novel_id,
        )
        qvec = vectors[0] if vectors else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("embedding 失败，仅关键词检索: %s", exc)
        qvec = None

    chapters = (
        await session.execute(
            select(Chapter).where(Chapter.novel_id == novel_id).order_by(Chapter.index)
        )
    ).scalars().all()

    keywords = set(extract_keywords(query, top_k=12))
    scored: list[tuple[Chapter, float]] = []
    for ch in chapters:
        if ch.id in exclude_chapter_ids:
            continue
        score = 0.0
        if qvec and ch.embedding_json:
            score += 0.7 * _cosine(qvec, ch.embedding_json)
        # 关键词
        blob = (ch.title or "") + "\n" + (ch.content or "")[:2000]
        hits = sum(1 for k in keywords if k in blob)
        if keywords:
            score += 0.3 * (hits / max(len(keywords), 1))
        if score > 0:
            scored.append((ch, score))

    scored.sort(key=lambda x: -x[1])
    results: list[tuple[Chapter, float, str]] = []
    for ch, score in scored[:top_k]:
        # 优先用章摘要
        summary = (
            await session.execute(
                select(Summary).where(
                    Summary.chapter_id == ch.id, Summary.level == "chapter"
                )
            )
        ).scalar_one_or_none()
        snippet = summary.content if summary else (ch.content or "")[:300]
        results.append((ch, score, snippet))
    return results
