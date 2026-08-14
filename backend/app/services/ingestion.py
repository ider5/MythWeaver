"""入库管线：分章→并发摘要→实体抽取→向量化。"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.llm.client import get_llm_client
from app.llm.cost_tracker import log_cost
from app.llm.prompts import render
from app.models import Chapter, Novel, StyleSample, Summary
from app.services import story_bible as bible_svc
from app.services.chapter_length import refresh_original_chapter_stats
from app.services.retrieval import embed_and_store, embed_and_store_batch
from app.services.tasks import TaskProgress, get_task_queue
from app.utils.chinese_text import (
    ParsedChapter,
    clean_text,
    count_chars,
    decode_bytes,
    parse_chapters,
    parse_directory_import,
)
from app.utils.json_extract import extract_json

logger = logging.getLogger(__name__)

# 临时导入缓存：token -> {chapters, title, raw_path}
_import_cache: dict[str, dict[str, Any]] = {}


def preview_from_text(raw: bytes | str, *, suggested_title: str = "未命名小说") -> dict[str, Any]:
    if isinstance(raw, bytes):
        text = decode_bytes(raw)
    else:
        text = raw
    text = clean_text(text)
    chapters = parse_chapters(text)
    token = uuid.uuid4().hex
    _import_cache[token] = {
        "chapters": chapters,
        "title": suggested_title,
        "text": text,
    }
    return {
        "title": suggested_title,
        "total_chars": count_chars(text),
        "chapter_count": len(chapters),
        "chapters": [
            {
                "index": c.index,
                "title": c.title,
                "volume": c.volume,
                "char_count": c.char_count,
                "preview": c.content[:200],
            }
            for c in chapters
        ],
        "import_token": token,
    }


def preview_from_files(files: list[tuple[str, bytes]], *, suggested_title: str = "未命名小说") -> dict[str, Any]:
    decoded: list[tuple[str, str]] = [(path, clean_text(decode_bytes(data))) for path, data in files]
    chapters = parse_directory_import(decoded)
    token = uuid.uuid4().hex
    full = "\n\n".join(c.content for c in chapters)
    _import_cache[token] = {"chapters": chapters, "title": suggested_title, "text": full}
    return {
        "title": suggested_title,
        "total_chars": count_chars(full),
        "chapter_count": len(chapters),
        "chapters": [
            {
                "index": c.index,
                "title": c.title,
                "volume": c.volume,
                "char_count": c.char_count,
                "preview": c.content[:200],
            }
            for c in chapters
        ],
        "import_token": token,
    }


def pop_import(token: str) -> dict[str, Any] | None:
    return _import_cache.pop(token, None)


def get_import(token: str) -> dict[str, Any] | None:
    return _import_cache.get(token)


async def confirm_import(
    session: AsyncSession,
    *,
    import_token: str,
    title: str | None = None,
    author: str | None = None,
    genre: str = "玄幻",
) -> Novel:
    data = pop_import(import_token)
    if data is None:
        raise ValueError("导入令牌无效或已过期")
    chapters: list[ParsedChapter] = data["chapters"]
    settings = get_settings()
    novel = Novel(
        title=title or data.get("title") or "未命名小说",
        author=author,
        genre=genre,
        status="imported",
        total_chars=sum(c.char_count for c in chapters),
        chapter_count=len(chapters),
    )
    session.add(novel)
    await session.flush()

    # 备份原文
    backup = settings.data_dir / "imports" / f"novel_{novel.id}.txt"
    backup.write_text(data.get("text") or "", encoding="utf-8")
    novel.source_path = str(backup)

    for c in chapters:
        session.add(
            Chapter(
                novel_id=novel.id,
                index=c.index,
                title=c.title,
                volume=c.volume,
                content=c.content,
                char_count=c.char_count,
                status="raw",
            )
        )
    await refresh_original_chapter_stats(session, novel)
    await session.commit()
    await session.refresh(novel)
    return novel


async def start_ingestion(session: AsyncSession, novel_id: int):
    novel = await session.get(Novel, novel_id)
    if novel is None:
        raise ValueError("小说不存在")
    novel.status = "ingesting"
    await session.commit()
    queue = get_task_queue()
    return await queue.enqueue(
        session, task_type="ingest", novel_id=novel_id, message="入库排队中"
    )


async def ingest_novel_handler(session: AsyncSession, task, progress: TaskProgress) -> dict:
    novel_id = task.novel_id
    assert novel_id
    settings = get_settings()
    novel = await session.get(Novel, novel_id)
    if novel is None:
        raise ValueError("小说不存在")

    chapters = (
        await session.execute(
            select(Chapter).where(Chapter.novel_id == novel_id).order_by(Chapter.index)
        )
    ).scalars().all()
    total = len(chapters)
    if total == 0:
        novel.status = "ready"
        await session.commit()
        return {"chapter_count": 0}

    sem = asyncio.Semaphore(settings.ingest_concurrency)
    done = 0
    lock = asyncio.Lock()

    # 顺序提交数据库会话不安全并发写同一 session；改为独立 session
    from app import db as db_mod

    async def process_one_isolated(ch_id: int) -> None:
        """摘要 + 实体抽取；向量化放到后续批量阶段。"""
        nonlocal done
        assert db_mod.SessionLocal
        async with sem:
            async with db_mod.SessionLocal() as s:
                ch = await s.get(Chapter, ch_id)
                n = await s.get(Novel, novel_id)
                if ch is None or n is None:
                    return
                # 已完成向量化：跳过，避免重复 embed
                if ch.status == "embedded" and ch.embedding_json:
                    async with lock:
                        done += 1
                        pct = 5 + done / total * 70
                        await progress.update(
                            s,
                            progress=pct,
                            message=f"跳过已向量化 {done}/{total}（第{ch.index}章）",
                        )
                    return
                if ch.status == "raw":
                    await _summarize_chapter(s, n, ch)
                    ch.status = "summarized"
                    await s.commit()
                if ch.status == "summarized":
                    await _extract_chapter(s, n, ch)
                    ch.status = "extracted"
                    await s.commit()
                async with lock:
                    done += 1
                    pct = 5 + done / total * 70
                    await progress.update(
                        s,
                        progress=pct,
                        message=f"已处理 {done}/{total} 章（第{ch.index}章 {ch.status}）",
                    )

    await progress.update(session, progress=3.0, message=f"开始入库，共 {total} 章")
    await asyncio.gather(*(process_one_isolated(ch.id) for ch in chapters))

    # 摘要/抽取在独立 session 提交；本会话 expire_on_commit=False，
    # identity map 里的 Chapter 仍可能停在 raw，必须过期后再向量化。
    session.expire_all()
    novel = await session.get(Novel, novel_id)
    if novel is None:
        raise ValueError("小说不存在")

    # 批量向量化（智谱等支持一次多 input；跳过已有 embedding_json 的章）
    await progress.update(session, progress=78.0, message="批量向量化…")
    await _batch_embed_novel(session, novel, progress)

    # 卷摘要
    await progress.update(session, progress=92.0, message="生成卷级摘要")
    await _build_volume_summaries(session, novel)

    # 文风样本
    await progress.update(session, progress=96.0, message="提取文风样本")
    await _extract_style_samples(session, novel)

    novel = await session.get(Novel, novel_id) or novel
    await refresh_original_chapter_stats(session, novel)
    novel.status = "ready"
    await session.commit()
    return {"chapter_count": total, "novel_id": novel_id}


async def _batch_embed_novel(
    session: AsyncSession, novel: Novel, progress: TaskProgress
) -> None:
    """对尚未向量化的章节批量 embed；已有 JSON 的只补写 vec0。"""
    from app.db import is_vec_available
    from app.services.retrieval import upsert_chapter_embedding

    chapters = (
        await session.execute(
            select(Chapter)
            .where(Chapter.novel_id == novel.id)
            .order_by(Chapter.index)
            .execution_options(populate_existing=True)
        )
    ).scalars().all()

    # 已有 JSON：仅补 vec（不调 API）
    if is_vec_available():
        for ch in chapters:
            if ch.embedding_json and ch.status in ("extracted", "embedded"):
                try:
                    await upsert_chapter_embedding(session, ch, ch.embedding_json)
                    ch.status = "embedded"
                except Exception as exc:  # noqa: BLE001
                    logger.debug("补写 vec0 失败 chapter=%s: %s", ch.index, exc)
        await session.commit()

    need_api: list[tuple[Chapter, str]] = []
    for ch in chapters:
        if ch.embedding_json:
            if ch.status != "embedded":
                ch.status = "embedded"
            continue
        if ch.status == "raw":
            continue
        text_for_embed = ch.content[:4000]
        summary = (
            await session.execute(
                select(Summary).where(
                    Summary.chapter_id == ch.id, Summary.level == "chapter"
                )
            )
        ).scalar_one_or_none()
        if summary:
            text_for_embed = summary.content
        need_api.append((ch, text_for_embed))

    if not need_api:
        await session.commit()
        return

    written = await embed_and_store_batch(session, need_api, novel_id=novel.id)
    for ch, _ in need_api:
        if ch.embedding_json:
            ch.status = "embedded"
    await session.commit()
    await progress.update(
        session,
        progress=88.0,
        message=f"向量化完成 {written}/{len(need_api)} 章",
    )


async def _summarize_chapter(session: AsyncSession, novel: Novel, ch: Chapter) -> None:
    existing = (
        await session.execute(
            select(Summary).where(Summary.chapter_id == ch.id, Summary.level == "chapter")
        )
    ).scalar_one_or_none()
    if existing:
        return
    client = get_llm_client()
    prompt = render(
        "summary.j2",
        title=ch.title,
        volume=ch.volume or "",
        content=ch.content[:8000],
    )
    result = await client.chat(
        [{"role": "user", "content": prompt}],
        endpoint=client.summary_endpoint(),
        temperature=0.3,
        purpose="summary",
    )
    session.add(
        Summary(
            novel_id=novel.id,
            chapter_id=ch.id,
            level="chapter",
            volume_key=ch.volume,
            content=result.text.strip(),
        )
    )
    await log_cost(
        session,
        purpose="summary",
        provider=result.provider,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        novel_id=novel.id,
    )
    await session.flush()


async def _extract_chapter(session: AsyncSession, novel: Novel, ch: Chapter) -> None:
    client = get_llm_client()
    prompt = render("extract.j2", title=ch.title, content=ch.content[:8000])
    result = await client.chat(
        [{"role": "user", "content": prompt}],
        endpoint=client.summary_endpoint(),
        temperature=0.2,
        purpose="extract",
    )
    try:
        data = extract_json(result.text)
    except Exception:  # noqa: BLE001
        data = {}
    if isinstance(data, dict):
        await bible_svc.merge_extraction(session, novel.id, data, chapter_index=ch.index)
    await log_cost(
        session,
        purpose="extract",
        provider=result.provider,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        novel_id=novel.id,
    )


async def _build_volume_summaries(session: AsyncSession, novel: Novel) -> None:
    chapters = (
        await session.execute(
            select(Chapter).where(Chapter.novel_id == novel.id).order_by(Chapter.index)
        )
    ).scalars().all()
    by_vol: dict[str, list[Chapter]] = {}
    for ch in chapters:
        key = ch.volume or "默认卷"
        by_vol.setdefault(key, []).append(ch)

    client = get_llm_client()
    for vol, chs in by_vol.items():
        existing = (
            await session.execute(
                select(Summary).where(
                    Summary.novel_id == novel.id,
                    Summary.level == "volume",
                    Summary.volume_key == vol,
                )
            )
        ).scalar_one_or_none()
        if existing:
            continue
        summaries = []
        for ch in chs:
            s = (
                await session.execute(
                    select(Summary).where(Summary.chapter_id == ch.id, Summary.level == "chapter")
                )
            ).scalar_one_or_none()
            if s:
                summaries.append(f"{ch.title}: {s.content}")
        if not summaries:
            continue
        prompt = render(
            "volume_summary.j2",
            volume=vol,
            chapter_summaries="\n".join(summaries)[:12000],
        )
        result = await client.chat(
            [{"role": "user", "content": prompt}],
            endpoint=client.summary_endpoint(),
            temperature=0.3,
            purpose="summary",
        )
        session.add(
            Summary(
                novel_id=novel.id,
                level="volume",
                volume_key=vol,
                content=result.text.strip(),
            )
        )
        await log_cost(
            session,
            purpose="summary",
            provider=result.provider,
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            novel_id=novel.id,
        )
    await session.commit()


async def _extract_style_samples(session: AsyncSession, novel: Novel) -> None:
    existing = (
        await session.execute(select(StyleSample).where(StyleSample.novel_id == novel.id))
    ).scalars().all()
    if existing:
        return
    chapters = (
        await session.execute(
            select(Chapter).where(Chapter.novel_id == novel.id).order_by(Chapter.index).limit(5)
        )
    ).scalars().all()
    if not chapters:
        return
    excerpts = "\n\n====\n\n".join(f"{c.title}\n{c.content[:1200]}" for c in chapters)
    client = get_llm_client()
    prompt = render("style.j2", excerpts=excerpts)
    try:
        result = await client.chat(
            [{"role": "user", "content": prompt}],
            endpoint=client.summary_endpoint(),
            temperature=0.3,
            purpose="style",
        )
        data = extract_json(result.text)
        samples = data.get("samples") if isinstance(data, dict) else None
        if samples:
            for s in samples[:3]:
                session.add(
                    StyleSample(
                        novel_id=novel.id,
                        content=s.get("content") or "",
                        reason=s.get("reason"),
                    )
                )
            await log_cost(
                session,
                purpose="style",
                provider=result.provider,
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                novel_id=novel.id,
            )
            await session.commit()
            return
    except Exception as exc:  # noqa: BLE001
        logger.warning("文风提取失败，使用启发式: %s", exc)

    for c in chapters[:3]:
        session.add(StyleSample(novel_id=novel.id, chapter_id=c.id, content=c.content[:350], reason="启发式截取"))
    await session.commit()


async def incremental_update_chapter(
    session: AsyncSession,
    chapter: Chapter,
    progress: TaskProgress | None = None,
) -> None:
    """新章确认入库后的增量更新。"""
    novel = await session.get(Novel, chapter.novel_id)
    if novel is None:
        return

    async def _p(pct: float, message: str) -> None:
        if progress is not None:
            # 独立短事务落库；业务事务持锁时跳过落库，SSE 仍靠内存推送
            await progress.update(session, progress=pct, message=message)

    # 重置状态以重新跑摘要/抽取/向量
    # 删除旧摘要（与后续重写同属一笔事务，失败可整体 rollback）
    old = (
        await session.execute(
            select(Summary).where(Summary.chapter_id == chapter.id, Summary.level == "chapter")
        )
    ).scalars().all()
    for s in old:
        await session.delete(s)
    await session.flush()
    chapter.status = "raw"
    await _p(15.0, "生成章节摘要…")
    await _summarize_chapter(session, novel, chapter)
    chapter.status = "summarized"
    await _p(40.0, "抽取实体与设定…")
    await _extract_chapter(session, novel, chapter)
    chapter.status = "extracted"
    summary = (
        await session.execute(
            select(Summary).where(Summary.chapter_id == chapter.id, Summary.level == "chapter")
        )
    ).scalar_one_or_none()
    text_for_embed = summary.content if summary else chapter.content[:4000]
    await _p(65.0, "向量化章节…")
    try:
        await embed_and_store(session, chapter, text_for_embed, novel_id=novel.id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("增量向量化失败: %s", exc)
    chapter.status = "embedded"
    novel.chapter_count = max(novel.chapter_count, chapter.index)
    # 按全书章节重算，避免修订/重试入库时重复累加
    char_sum = (
        await session.execute(
            select(Chapter.char_count).where(Chapter.novel_id == novel.id)
        )
    ).scalars().all()
    novel.total_chars = sum(c or 0 for c in char_sum)
    await refresh_original_chapter_stats(session, novel)
    await session.commit()
    await _p(80.0, "章节向量化完成")
