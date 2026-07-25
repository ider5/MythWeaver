"""向量检索 + 关键词混合检索。"""

from __future__ import annotations

import logging
import math
import struct
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import is_vec_available
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


def serialize_vec(vector: list[float]) -> bytes:
    """sqlite-vec float32 blob。"""
    return struct.pack(f"{len(vector)}f", *vector)


def _distance_to_score(distance: float) -> float:
    """L2 距离 → (0, 1] 相似度分。"""
    return 1.0 / (1.0 + max(float(distance), 0.0))


async def upsert_chapter_embedding(
    session: AsyncSession,
    chapter: Chapter,
    vector: list[float],
) -> None:
    chapter.embedding_json = vector
    if not is_vec_available():
        await session.flush()
        return
    try:
        await session.execute(
            text("DELETE FROM chapter_embeddings WHERE chapter_id = :cid"),
            {"cid": chapter.id},
        )
        await session.execute(
            text(
                "INSERT INTO chapter_embeddings(chapter_id, embedding) "
                "VALUES (:cid, :emb)"
            ),
            {"cid": chapter.id, "emb": serialize_vec(vector)},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("vec upsert 失败，已保留 embedding_json: %s", exc)
    await session.flush()


async def delete_chapter_embedding(session: AsyncSession, chapter_id: int) -> None:
    """删除 vec0 中该章向量；JSON 向量随 Chapter 行删除即可。"""
    if not is_vec_available():
        return
    try:
        await session.execute(
            text("DELETE FROM chapter_embeddings WHERE chapter_id = :cid"),
            {"cid": chapter_id},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("删除 chapter_embeddings 失败 chapter_id=%s: %s", chapter_id, exc)


async def backfill_vec_from_json(session: AsyncSession) -> int:
    """把已有 embedding_json 回填进 vec0（跳过已存在 / 维度不符）。返回写入条数。"""
    if not is_vec_available():
        return 0
    settings = get_settings()
    dims = settings.embedding_dims
    try:
        existing_rows = (
            await session.execute(text("SELECT chapter_id FROM chapter_embeddings"))
        ).fetchall()
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取 chapter_embeddings 失败，跳过回填: %s", exc)
        return 0
    existing = {int(r[0]) for r in existing_rows}

    chapters = (
        await session.execute(select(Chapter).where(Chapter.embedding_json.is_not(None)))
    ).scalars().all()

    written = 0
    for ch in chapters:
        if ch.id is None or ch.id in existing:
            continue
        vec = ch.embedding_json
        if not isinstance(vec, list) or len(vec) != dims:
            continue
        try:
            await session.execute(
                text(
                    "INSERT INTO chapter_embeddings(chapter_id, embedding) "
                    "VALUES (:cid, :emb)"
                ),
                {"cid": ch.id, "emb": serialize_vec([float(x) for x in vec])},
            )
            written += 1
        except Exception as exc:  # noqa: BLE001
            logger.debug("回填 chapter_id=%s 失败: %s", ch.id, exc)
    if written:
        await session.flush()
    return written


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


async def embed_and_store_batch(
    session: AsyncSession,
    items: list[tuple[Chapter, str]],
    *,
    novel_id: int,
) -> int:
    """批量向量化并写入；返回成功写入条数。智谱等支持一次多 input。"""
    if not items:
        return 0
    settings = get_settings()
    batch_size = max(1, settings.embedding_batch_size)
    client = get_llm_client()
    written = 0

    for start in range(0, len(items), batch_size):
        chunk = items[start : start + batch_size]
        texts = [t[:6000] for _, t in chunk]
        try:
            vectors, tokens = await client.embed(texts)
        except Exception as exc:  # noqa: BLE001
            logger.warning("批量向量化失败（batch@%s）：%s", start, exc)
            continue
        if len(vectors) != len(chunk):
            logger.warning(
                "批量向量数量不匹配：期望 %s 得到 %s",
                len(chunk),
                len(vectors),
            )
        n = min(len(vectors), len(chunk))
        for i in range(n):
            ch, _ = chunk[i]
            await upsert_chapter_embedding(session, ch, vectors[i])
            written += 1
        await log_cost(
            session,
            purpose="embed",
            provider="openai",
            model=settings.embedding_model,
            input_tokens=tokens,
            novel_id=novel_id,
        )
        await session.flush()
    return written


async def _vec_knn_scores(
    session: AsyncSession,
    novel_id: int,
    qvec: list[float],
    *,
    top_k: int,
    exclude_chapter_ids: set[int],
) -> dict[int, float] | None:
    """用 sqlite-vec 近邻检索，返回 {chapter_id: similarity_score}；失败返回 None。"""
    if not is_vec_available() or not qvec:
        return None
    # 多取一些以便排除与 novel 过滤后仍够 top_k
    k = max(top_k + len(exclude_chapter_ids) + 16, top_k * 3)
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT ve.chapter_id, ve.distance
                    FROM chapter_embeddings AS ve
                    JOIN chapters AS c ON c.id = ve.chapter_id
                    WHERE c.novel_id = :nid
                      AND ve.embedding MATCH :emb
                      AND k = :k
                    """
                ),
                {"nid": novel_id, "emb": serialize_vec(qvec), "k": k},
            )
        ).fetchall()
    except Exception as exc:  # noqa: BLE001
        logger.warning("vec0 近邻检索失败，回退 JSON 余弦: %s", exc)
        return None

    scores: dict[int, float] = {}
    for chapter_id, distance in rows:
        cid = int(chapter_id)
        if cid in exclude_chapter_ids:
            continue
        scores[cid] = _distance_to_score(distance)
        if len(scores) >= top_k * 4:
            break
    return scores


async def hybrid_search(
    session: AsyncSession,
    novel_id: int,
    query: str,
    *,
    top_k: int = 8,
    exclude_chapter_ids: Optional[set[int]] = None,
) -> list[tuple[Chapter, float, str]]:
    """返回 [(chapter, score, snippet)]。有向量时优先 sqlite-vec，否则 JSON 余弦。"""
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
    by_id = {ch.id: ch for ch in chapters if ch.id is not None}

    keywords = set(extract_keywords(query, top_k=12))
    vec_scores: dict[int, float] | None = None
    if qvec:
        vec_scores = await _vec_knn_scores(
            session,
            novel_id,
            qvec,
            top_k=top_k,
            exclude_chapter_ids=exclude_chapter_ids,
        )

    scored: list[tuple[Chapter, float]] = []
    for ch in chapters:
        if ch.id in exclude_chapter_ids:
            continue
        score = 0.0
        if qvec:
            if vec_scores is not None:
                score += 0.7 * vec_scores.get(ch.id, 0.0)
            elif ch.embedding_json:
                score += 0.7 * _cosine(qvec, ch.embedding_json)
        blob = (ch.title or "") + "\n" + (ch.content or "")[:2000]
        hits = sum(1 for k in keywords if k in blob)
        if keywords:
            score += 0.3 * (hits / max(len(keywords), 1))
        if score > 0:
            scored.append((ch, score))

    # vec 命中但关键词为 0 时仍应纳入（上面已覆盖）；若 vec_scores 有而章节循环未加满，补齐
    if vec_scores:
        present = {ch.id for ch, _ in scored}
        for cid, vscore in vec_scores.items():
            if cid in present or cid in exclude_chapter_ids:
                continue
            ch = by_id.get(cid)
            if ch is None:
                continue
            score = 0.7 * vscore
            if score > 0:
                scored.append((ch, score))

    scored.sort(key=lambda x: -x[1])
    results: list[tuple[Chapter, float, str]] = []
    for ch, score in scored[:top_k]:
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
