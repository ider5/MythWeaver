"""生成后的轻量质量信号。

不替代 Critic，也不调用模型：

- 文风漂移只对照已保存的 StyleSample
- 未回收伏笔在写作台常驻；计划回收章临近、到期或逾期时给出提醒
- 篇幅偏离目标、章末没落到大纲悬念钩子，记为严重问题，连续生成会因此停下
- 其余提示（文风、伏笔、套话）不阻断后续章节
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import StyleSample
from app.services import story_bible as bible_svc
from app.services.consistency import find_ai_voice_cliches, find_chapter_meta_refs
from app.utils.chinese_text import count_chars

APPROACH_WINDOW = 2
SPOT_CHECK_EVERY = 3
LENGTH_LOW = 0.8
LENGTH_HIGH = 1.2
_BLOCKING_KINDS = {"length", "end_hook"}
_RESOLVED_MARK = "已回收"

_SENT_SPLIT = re.compile(r"[。！？!?]+")
_DIALOGUE = re.compile(r"「[^」]{0,80}」|“[^”]{0,80}”|\"[^\"]{0,80}\"")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]{2,}")
_ELLIPSIS = re.compile(r"……|\.{3,}|…")
_FIRST = re.compile(r"我")
_THIRD = re.compile(r"[他她]")
_PARTICLE = frozenset("的了着与和或及并在把被将就也还又这那其")


def spot_check_positions(count: int, *, every: int = SPOT_CHECK_EVERY) -> set[int]:
    """抽查下标：首章、末章，以及每隔 `every` 章。"""
    if count <= 0:
        return set()
    chosen = {0, count - 1}
    step = max(1, int(every))
    for index in range(0, count, step):
        chosen.add(index)
    return {index for index in chosen if 0 <= index < count}


def chapters_for_full_critic(count: int, *, spot_check: bool) -> set[int]:
    if count <= 0:
        return set()
    if not spot_check:
        return set(range(count))
    return spot_check_positions(count)


def _hint(
    *,
    id: str,
    kind: str,
    severity: str,
    message: str,
    detail: str | None = None,
) -> dict[str, Any]:
    return {
        "id": id,
        "kind": kind,
        "severity": severity,
        "message": message,
        "detail": detail,
    }


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENT_SPLIT.split(text or "") if part.strip()]


def _dialogue_ratio(text: str) -> float:
    body = text or ""
    total = count_chars(body)
    if total <= 0:
        return 0.0
    spoken = sum(count_chars(match.group(0)) for match in _DIALOGUE.finditer(body))
    return spoken / total


def _style_profile(text: str) -> dict[str, float]:
    sentences = _sentences(text)
    lengths = [count_chars(sentence) for sentence in sentences if count_chars(sentence) > 0]
    avg = (sum(lengths) / len(lengths)) if lengths else 0.0
    return {
        "avg_sentence": avg,
        "sentence_count": float(len(lengths)),
        "dialogue": _dialogue_ratio(text),
        "first": float(len(_FIRST.findall(text or ""))),
        "third": float(len(_THIRD.findall(text or ""))),
        "ellipsis": float(len(_ELLIPSIS.findall(text or ""))),
        "chars": float(count_chars(text or "")),
    }


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def style_drift_hints(content: str, references: list[str]) -> list[dict[str, Any]]:
    """对照文风样本。没有样本、或正文太短时不提示。"""
    samples = [text for text in references if count_chars(text or "") >= 40]
    if not samples or count_chars(content or "") < 80:
        return []

    gen = _style_profile(content)
    refs = [_style_profile(text) for text in samples]
    if gen["sentence_count"] < 3:
        return []

    hints: list[dict[str, Any]] = []
    ref_sentence = _median([row["avg_sentence"] for row in refs if row["avg_sentence"] > 0])
    gen_sentence = gen["avg_sentence"]
    if ref_sentence >= 12 and gen_sentence > 0:
        ratio = gen_sentence / ref_sentence
        gap = abs(gen_sentence - ref_sentence)
        if gap >= 8 and (ratio < 0.55 or ratio > 1.85):
            direction = "偏短" if gen_sentence < ref_sentence else "偏长"
            hints.append(
                _hint(
                    id="style:sentence",
                    kind="style",
                    severity="info",
                    message=f"句子{direction}于文风样本（本章均长 {gen_sentence:.0f} 字，样本约 {ref_sentence:.0f} 字）",
                    detail="对照已保存的文风样本，不改写正文",
                )
            )

    ref_dialogue = sum(row["dialogue"] for row in refs) / len(refs)
    gen_dialogue = gen["dialogue"]
    if max(ref_dialogue, gen_dialogue) >= 0.12 and abs(gen_dialogue - ref_dialogue) >= 0.22:
        direction = "少" if gen_dialogue < ref_dialogue else "多"
        hints.append(
            _hint(
                id="style:dialogue",
                kind="style",
                severity="info",
                message=(
                    f"对白比文风样本{direction}"
                    f"（本章 {gen_dialogue:.0%}，样本约 {ref_dialogue:.0%}）"
                ),
                detail="对照已保存的文风样本",
            )
        )

    ref_first = sum(row["first"] for row in refs)
    ref_third = sum(row["third"] for row in refs)
    ref_total = ref_first + ref_third
    gen_total = gen["first"] + gen["third"]
    if ref_total >= 8 and gen_total >= 6:
        ref_ratio = ref_first / ref_total
        gen_ratio = gen["first"] / gen_total
        if ref_ratio >= 0.72 and gen_ratio <= 0.25:
            hints.append(
                _hint(
                    id="style:person",
                    kind="style",
                    severity="info",
                    message="叙述人称偏离文风样本：样本偏第一人称，本章几乎是第三人称",
                    detail="对照已保存的文风样本",
                )
            )
        elif ref_ratio <= 0.28 and gen_ratio >= 0.72:
            hints.append(
                _hint(
                    id="style:person",
                    kind="style",
                    severity="info",
                    message="叙述人称偏离文风样本：样本偏第三人称，本章几乎是第一人称",
                    detail="对照已保存的文风样本",
                )
            )

    ref_chars = sum(row["chars"] for row in refs) or 1
    gen_chars = gen["chars"] or 1
    ref_ellipsis = sum(row["ellipsis"] for row in refs) / ref_chars * 500
    gen_ellipsis = gen["ellipsis"] / gen_chars * 500
    if ref_ellipsis < 0.3 and gen["ellipsis"] >= 4 and gen_ellipsis >= 2.5:
        hints.append(
            _hint(
                id="style:ellipsis",
                kind="style",
                severity="info",
                message="省略号明显密于文风样本",
                detail="对照已保存的文风样本",
            )
        )
    return hints[:3]


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _attr(thread: Any, key: str, default: Any = None) -> Any:
    if isinstance(thread, dict):
        return thread.get(key, default)
    return getattr(thread, key, default)


def _is_resolved(thread: Any, chapter_index: int) -> bool:
    status = str(_attr(thread, "status") or "").strip()
    if _RESOLVED_MARK in status:
        return True
    resolved = _as_int(_attr(thread, "resolved_chapter"))
    return resolved is not None and resolved <= chapter_index


def _not_yet_introduced(thread: Any, chapter_index: int) -> bool:
    introduced = _as_int(_attr(thread, "introduced_chapter"))
    return introduced is not None and introduced > chapter_index


def _due_state(planned: int | None, chapter_index: int) -> str | None:
    if planned is None:
        return None
    delta = planned - chapter_index
    if delta > APPROACH_WINDOW:
        return None
    if delta > 0:
        return "approaching"
    if delta == 0:
        return "due"
    return "overdue"


def _thread_note(thread: Any, chapter_index: int, due: str | None) -> str:
    introduced = _as_int(_attr(thread, "introduced_chapter"))
    planned = _as_int(_attr(thread, "planned_resolve_chapter"))
    parts: list[str] = []
    if introduced is not None:
        parts.append(f"第{introduced}章出现")
    if planned is None:
        parts.append("尚未安排回收")
        return " · ".join(parts)
    if due == "due":
        parts.append("计划在本章回收")
    elif due == "approaching":
        parts.append(f"计划第{planned}章回收，还剩 {planned - chapter_index} 章")
    elif due == "overdue":
        parts.append(f"计划第{planned}章回收，已逾期 {chapter_index - planned} 章")
    else:
        parts.append(f"计划第{planned}章回收")
    return " · ".join(parts)


def _visible_threads(threads: list[Any], chapter_index: int) -> list[Any]:
    visible: list[Any] = []
    for thread in threads:
        title = str(_attr(thread, "title") or "").strip()
        if not title:
            continue
        if _is_resolved(thread, chapter_index) or _not_yet_introduced(thread, chapter_index):
            continue
        visible.append(thread)
    return visible


def open_thread_views(threads: list[Any], chapter_index: int) -> list[dict[str, Any]]:
    """写作台要看的未回收线索。已回收、或尚未出场的不列入。"""
    rows: list[dict[str, Any]] = []
    for thread in _visible_threads(threads, chapter_index):
        planned = _as_int(_attr(thread, "planned_resolve_chapter"))
        due = _due_state(planned, chapter_index)
        rows.append(
            {
                "id": int(_attr(thread, "id") or 0),
                "title": str(_attr(thread, "title") or "").strip(),
                "thread_type": str(_attr(thread, "thread_type") or "伏笔"),
                "status": str(_attr(thread, "status") or "未回收"),
                "introduced_chapter": _as_int(_attr(thread, "introduced_chapter")),
                "planned_resolve_chapter": planned,
                "due": due,
                "note": _thread_note(thread, chapter_index, due),
            }
        )
    rank = {"overdue": 0, "due": 1, "approaching": 2}
    rows.sort(key=lambda row: (rank.get(row["due"] or "", 3), row["planned_resolve_chapter"] or 10**6, row["id"]))
    return rows


def thread_due_hints(threads: list[Any], chapter_index: int) -> list[dict[str, Any]]:
    """只提示计划回收章已经临近、到期或逾期的线。普通未回收线不重复刷屏。"""
    hints: list[dict[str, Any]] = []
    for row in open_thread_views(threads, chapter_index):
        due = row["due"]
        if due not in {"approaching", "due", "overdue"}:
            continue
        severity = "info" if due == "approaching" else "warning"
        hints.append(
            _hint(
                id=f"thread:{row['id']}:{due}",
                kind="thread",
                severity=severity,
                message=f"「{row['title']}」{row['note']}",
                detail=row["thread_type"],
            )
        )
    return hints[:6]


def length_hint(content: str, target_chars: int) -> dict[str, Any] | None:
    """偏离目标 ±20% 视为严重。目标未知时不判断。"""
    target = int(target_chars or 0)
    if target <= 0:
        return None
    actual = count_chars(content or "")
    low = int(target * LENGTH_LOW)
    high = int(target * LENGTH_HIGH)
    if low <= actual <= high:
        return None
    if actual < low:
        message = f"本章约 {actual} 字，短于目标 {target} 字（允许 {low}–{high}）"
    else:
        message = f"本章约 {actual} 字，长于目标 {target} 字（允许 {low}–{high}）"
    return _hint(
        id="length",
        kind="length",
        severity="error",
        message=message,
        detail=f"目标 {target} 字，允许偏差 ±20%",
    )


def _hook_tokens(hook: str) -> list[str]:
    tokens: list[str] = []
    for run in _CJK_RUN.findall(hook or ""):
        if len(run) == 2:
            tokens.append(run)
            continue
        for index in range(0, len(run) - 1, 2):
            token = run[index : index + 2]
            if len(token) < 2 or token[0] in _PARTICLE:
                continue
            tokens.append(token)
    return list(dict.fromkeys(tokens))


def end_hook_hint(content: str, suspense_hook: str) -> dict[str, Any] | None:
    """大纲写了悬念钩子，但章末没有落到这些词上。没写钩子时不判断。"""
    hook = (suspense_hook or "").strip()
    tokens = _hook_tokens(hook)
    if not tokens:
        return None
    ending = (content or "")[-500:]
    hits = [token for token in tokens if token in ending]
    needed = 1 if len(tokens) <= 3 else max(1, int(len(tokens) * 0.34))
    if len(hits) >= needed:
        return None
    shown = hook if len(hook) <= 42 else hook[:42] + "…"
    return _hint(
        id="end_hook",
        kind="end_hook",
        severity="error",
        message=f"章末没有落到悬念钩子：{shown}",
        detail="只检查最后约 500 字是否带上钩子里的词",
    )


def local_rule_hints(content: str) -> list[dict[str, Any]]:
    """未跑 Critic 时，把已有规则检查摊开。警告级，不单独停下连续生成。"""
    hints: list[dict[str, Any]] = []
    for issue in find_chapter_meta_refs(content):
        hints.append(
            _hint(
                id="local:chapter_meta",
                kind="local",
                severity="warning",
                message=issue.get("message") or "正文出现章号指称",
                detail=issue.get("detail"),
            )
        )
    for issue in find_ai_voice_cliches(content):
        hints.append(
            _hint(
                id="local:ai_voice",
                kind="local",
                severity="warning",
                message=issue.get("message") or "正文有套话",
                detail=issue.get("detail"),
            )
        )
    return hints


def blocking_message(signals: dict[str, Any] | None) -> str | None:
    """篇幅或章末钩子未通过时返回暂停原因。文风和伏笔提醒不在此列。"""
    if not signals:
        return None
    for hint in signals.get("hints") or []:
        if not isinstance(hint, dict):
            continue
        if str(hint.get("severity") or "").lower() != "error":
            continue
        if hint.get("kind") not in _BLOCKING_KINDS:
            continue
        message = str(hint.get("message") or "").strip()
        if message:
            return message
    return None


def assemble_signals(
    *,
    chapter_index: int,
    content: str,
    references: list[str],
    threads: list[Any],
    target_chars: int,
    suspense_hook: str,
    include_local_rules: bool,
) -> dict[str, Any]:
    hints: list[dict[str, Any]] = []
    length = length_hint(content, target_chars)
    if length:
        hints.append(length)
    hook = end_hook_hint(content, suspense_hook)
    if hook:
        hints.append(hook)
    hints.extend(thread_due_hints(threads, chapter_index))
    hints.extend(style_drift_hints(content, references))
    if include_local_rules:
        hints.extend(local_rule_hints(content))
    return {
        "chapter_index": int(chapter_index),
        "critical": any(hint["severity"] == "error" for hint in hints),
        "hints": hints,
    }


async def _style_references(session: AsyncSession, novel_id: int) -> list[str]:
    rows = (
        await session.execute(
            select(StyleSample)
            .where(StyleSample.novel_id == novel_id)
            .order_by(StyleSample.id)
            .limit(4)
        )
    ).scalars().all()
    return [row.content for row in rows if (row.content or "").strip()]


async def assess_chapter_quality(
    session: AsyncSession,
    novel_id: int,
    content: str,
    *,
    chapter_index: int,
    target_chars: int = 0,
    suspense_hook: str = "",
    include_local_rules: bool = False,
) -> dict[str, Any]:
    references = await _style_references(session, novel_id)
    bible = await bible_svc.list_bible(session, novel_id)
    return assemble_signals(
        chapter_index=chapter_index,
        content=content,
        references=references,
        threads=bible["plot_threads"],
        target_chars=target_chars,
        suspense_hook=suspense_hook,
        include_local_rules=include_local_rules,
    )


async def list_open_threads(
    session: AsyncSession,
    novel_id: int,
    chapter_index: int,
) -> dict[str, Any]:
    bible = await bible_svc.list_bible(session, novel_id)
    return {
        "chapter_index": int(chapter_index),
        "threads": open_thread_views(bible["plot_threads"], chapter_index),
    }
