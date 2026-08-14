"""原作单章篇幅统计、目标字数与分段规划。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Chapter, Novel
from app.utils.chinese_text import count_chars, count_tokens

CHAPTER_LENGTH_MIN = 1500
CHAPTER_LENGTH_MAX = 30000
DEFAULT_TARGET_CHARS = 3000
TOKEN_PER_CHAR = 1.5
TOKEN_MARGIN = 1.2


@dataclass(frozen=True)
class LengthStats:
    median: int
    avg: int


@dataclass(frozen=True)
class ChapterSegment:
    index: int  # 1-based
    total: int
    target_chars: int
    key_points: list[str] = field(default_factory=list)
    is_last: bool = True


def clamp_target_chars(
    n: int,
    *,
    min_chars: int = CHAPTER_LENGTH_MIN,
    max_chars: int = CHAPTER_LENGTH_MAX,
) -> int:
    return max(min_chars, min(max_chars, int(n)))


def _median(values: list[int]) -> int:
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return 0
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) // 2


def compute_original_length_stats(
    char_counts: list[int],
    *,
    min_chars: int = CHAPTER_LENGTH_MIN,
    max_chars: int = CHAPTER_LENGTH_MAX,
) -> tuple[int, int]:
    """返回 (median, avg)。先剔除区间外异常章；若全部异常则夹紧后再统计。"""
    counts = [int(c) for c in char_counts if c and int(c) > 0]
    if not counts:
        return 0, 0
    in_range = [c for c in counts if min_chars <= c <= max_chars]
    used = in_range if in_range else [clamp_target_chars(c, min_chars=min_chars, max_chars=max_chars) for c in counts]
    avg = int(round(sum(used) / len(used)))
    med = _median(used)
    return (
        clamp_target_chars(med, min_chars=min_chars, max_chars=max_chars),
        clamp_target_chars(avg, min_chars=min_chars, max_chars=max_chars),
    )


def estimate_generation_max_tokens(
    target_chars: int,
    *,
    min_tokens: int = 1024,
    max_tokens: int = 8000,
) -> int:
    raw = int(max(1, target_chars) * TOKEN_PER_CHAR * TOKEN_MARGIN)
    return max(min_tokens, min(max_tokens, raw))


def ending_slice(text: str, max_chars: int = 2000) -> str:
    t = text or ""
    if max_chars <= 0 or len(t) <= max_chars:
        return t
    return t[-max_chars:]


def take_text_tail(text: str, max_tokens: int) -> str:
    """取文本末尾，使 token 数不超过预算。"""
    text = text or ""
    if max_tokens <= 0 or not text:
        return ""
    # 明显超长时先按字数切尾，避免整章 tiktoken
    if len(text) > max_tokens * 2:
        n = max(1, int(max_tokens / TOKEN_PER_CHAR) * 2)
        text = text[-min(len(text), n) :]
    if count_tokens(text) <= max_tokens:
        return text
    n = max(1, int(max_tokens / TOKEN_PER_CHAR))
    n = min(n, len(text))
    tail = text[-n:]
    while tail and count_tokens(tail) > max_tokens:
        nxt = max(1, int(len(tail) * 0.85))
        if nxt >= len(tail):
            nxt = len(tail) - 1
        tail = text[-nxt:]
        if nxt <= 24:
            break
    return tail


def sample_content_for_critic(content: str, *, budget_chars: int = 8000) -> str:
    """头 + 中段抽样 + 尾，避免长章整章送审。"""
    text = content or ""
    if count_chars(text) <= budget_chars:
        return text
    head = max(200, budget_chars // 3)
    mid_len = max(200, budget_chars // 3)
    tail = max(200, budget_chars - head - mid_len)
    if head + mid_len + tail > len(text):
        return text
    mid_start = max(0, (len(text) - mid_len) // 2)
    return (
        text[:head]
        + "\n\n……（中段抽样）……\n\n"
        + text[mid_start : mid_start + mid_len]
        + "\n\n……（章尾）……\n\n"
        + text[-tail:]
    )


def _chunk_points(points: list[str], n: int) -> list[list[str]]:
    groups: list[list[str]] = [[] for _ in range(max(1, n))]
    if not points:
        return groups
    base, rem = divmod(len(points), n)
    idx = 0
    for i in range(n):
        take = base + (1 if i < rem else 0)
        groups[i] = points[idx : idx + take]
        idx += take
    return groups


def _split_int(total: int, n: int) -> list[int]:
    n = max(1, n)
    base, rem = divmod(max(0, total), n)
    return [base + (1 if i < rem else 0) for i in range(n)]


def plan_chapter_segments(
    target_chars: int,
    key_points: list[str] | None = None,
    *,
    threshold: int | None = None,
    segment_target: int | None = None,
) -> list[ChapterSegment]:
    """短章单段；长章按要点/字数拆段，每段约 2500–4000 字。"""
    if threshold is None or segment_target is None:
        settings = get_settings()
        if threshold is None:
            threshold = settings.chapter_segment_threshold
        if segment_target is None:
            segment_target = settings.segment_target_chars
    points = [str(p).strip() for p in (key_points or []) if str(p).strip()]
    target_chars = max(1, int(target_chars))
    if target_chars <= int(threshold):
        return [
            ChapterSegment(
                index=1,
                total=1,
                target_chars=target_chars,
                key_points=points,
                is_last=True,
            )
        ]

    segment_target = max(1, int(segment_target))
    n_by_chars = max(2, math.ceil(target_chars / segment_target))
    n = max(n_by_chars, len(points)) if points else n_by_chars
    min_seg = 2500
    while n > 2 and (target_chars / n) < min_seg:
        n -= 1

    groups = _chunk_points(points, n)
    sizes = _split_int(target_chars, n)
    return [
        ChapterSegment(
            index=i + 1,
            total=n,
            target_chars=sizes[i],
            key_points=groups[i],
            is_last=i == n - 1,
        )
        for i in range(n)
    ]


async def refresh_original_chapter_stats(session: AsyncSession, novel: Novel) -> LengthStats:
    """按已入库非生成章刷新 Novel.median/avg_chapter_chars。不自行 commit。"""
    settings = get_settings()
    rows = (
        await session.execute(
            select(Chapter.char_count).where(
                Chapter.novel_id == novel.id,
                Chapter.is_generated.is_(False),
            )
        )
    ).scalars().all()
    med, avg = compute_original_length_stats(
        [int(c or 0) for c in rows],
        min_chars=settings.chapter_length_min,
        max_chars=settings.chapter_length_max,
    )
    novel.median_chapter_chars = med
    novel.avg_chapter_chars = avg
    return LengthStats(median=med, avg=avg)


async def resolve_target_chars(
    session: AsyncSession,
    novel: Novel,
    override: int | None = None,
) -> int:
    settings = get_settings()
    if override is not None and int(override) > 0:
        return clamp_target_chars(
            int(override),
            min_chars=settings.chapter_length_min,
            max_chars=settings.chapter_length_max,
        )
    cached = int(novel.median_chapter_chars or 0) or int(novel.avg_chapter_chars or 0)
    if cached <= 0:
        stats = await refresh_original_chapter_stats(session, novel)
        cached = stats.median or stats.avg
    if cached <= 0:
        cached = DEFAULT_TARGET_CHARS
    return clamp_target_chars(
        cached,
        min_chars=settings.chapter_length_min,
        max_chars=settings.chapter_length_max,
    )
