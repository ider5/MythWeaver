"""从零开书：不导入原稿，由前提播种 Story Bible。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.client import get_llm_client
from app.llm.cost_tracker import log_cost
from app.llm.prompts import render
from app.models import Novel
from app.services import story_bible as bible_svc
from app.utils.json_extract import extract_json

IMPORT_ORIGIN = "import"
SCRATCH_ORIGIN = "scratch"
ORIGINS = (IMPORT_ORIGIN, SCRATCH_ORIGIN)

SCRATCH_INGEST_DETAIL = "从零开书没有原稿，不能入库。请播种设定后生成大纲与开篇。"
NOT_SCRATCH_DETAIL = "只有从零开书可以播种设定。"


class ScratchError(Exception):
    def __init__(self, detail: str, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def is_scratch_origin(origin: str | None) -> bool:
    return (origin or IMPORT_ORIGIN) == SCRATCH_ORIGIN


def normalize_origin(origin: str | None) -> str:
    value = (origin or IMPORT_ORIGIN).strip()
    if value not in ORIGINS:
        raise ValueError("origin 仅支持 import 或 scratch")
    return value


async def create_scratch_novel(
    session: AsyncSession,
    *,
    title: str,
    genre: str,
    premise: str,
    writing_style: str,
    author: str | None = None,
) -> Novel:
    name = title.strip()
    if not name:
        raise ScratchError("请填写书名", 422)
    idea = premise.strip()
    if len(idea) < 8:
        raise ScratchError("前提至少 8 个字", 422)
    style = writing_style.strip()
    if len(style) < 2:
        raise ScratchError("请写明文风", 422)
    novel = Novel(
        title=name,
        author=(author or "").strip() or None,
        genre=(genre or "玄幻").strip() or "玄幻",
        role="manuscript",
        origin=SCRATCH_ORIGIN,
        premise=idea,
        writing_style=style,
        status="blank",
        chapter_count=0,
        total_chars=0,
    )
    session.add(novel)
    await session.commit()
    await session.refresh(novel)
    return novel


def _usable_rows(rows: object, key: str) -> list[dict]:
    if not isinstance(rows, list):
        return []
    kept: list[dict] = []
    for row in rows:
        if isinstance(row, dict) and str(row.get(key) or "").strip():
            kept.append(row)
    return kept


async def seed_scratch_bible(session: AsyncSession, novel_id: int) -> dict:
    """用前提生成 Story Bible 种子。不创建章节，也不要求入库。"""
    novel = await session.get(Novel, novel_id)
    if novel is None:
        raise ScratchError("小说不存在", 404)
    if not is_scratch_origin(novel.origin):
        raise ScratchError(NOT_SCRATCH_DETAIL, 409)
    premise = (novel.premise or "").strip()
    if len(premise) < 8:
        raise ScratchError("请先写下开书前提", 400)
    genre = novel.genre or "玄幻"
    style = (novel.writing_style or "").strip() or "口语化网文，短句"
    await session.commit()

    prompt = render(
        "seed_bible.j2",
        genre=genre,
        premise=premise,
        writing_style=style,
    )
    client = get_llm_client()
    try:
        result = await client.chat(
            [{"role": "user", "content": prompt}],
            endpoint=client.summary_endpoint(),
            temperature=0.4,
            purpose="bible_seed",
        )
    except Exception as exc:  # noqa: BLE001
        raise ScratchError(f"设定生成失败：{exc}", 502) from exc

    await log_cost(
        session,
        purpose="bible_seed",
        provider=result.provider,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        novel_id=novel_id,
    )
    await session.commit()

    try:
        data = extract_json(result.text)
    except Exception as exc:  # noqa: BLE001
        raise ScratchError("设定种子无法解析，请重试", 502) from exc
    if not isinstance(data, dict):
        raise ScratchError("设定种子无法解析，请重试", 502)

    characters = _usable_rows(data.get("characters"), "name")
    worlds = _usable_rows(data.get("world_settings"), "content")
    threads = _usable_rows(data.get("plot_threads"), "title")
    if not characters and not worlds and not threads:
        raise ScratchError("设定种子为空，请重试", 502)

    novel = await session.get(Novel, novel_id)
    if novel is None:
        raise ScratchError("小说不存在", 404)
    await bible_svc.merge_extraction(
        session,
        novel_id,
        {
            "characters": characters,
            "world_settings": worlds,
            "plot_threads": threads,
        },
    )
    if novel.status in ("blank", "imported"):
        novel.status = "seeded"
    await session.commit()
    bible = await bible_svc.list_bible(session, novel_id)
    await session.refresh(novel)
    return {"novel": novel, **bible}
