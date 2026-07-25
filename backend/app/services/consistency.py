"""一致性校验 + Critic 自检回路。"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.client import get_llm_client
from app.llm.cost_tracker import log_cost
from app.llm.prompts import render
from app.models import Novel
from app.schemas.generation import ConsistencyIssue, ConsistencyReport
from app.services import story_bible as bible_svc
from app.utils.json_extract import extract_json

# 正文内章号元指称（不含仅作首行标题的情况）
_CHAPTER_NUM_META = re.compile(
    r"第[零〇一二三四五六七八九十百千万两0-9]+章"
)
_CHAPTER_REL_META = re.compile(
    r"(?:上一章|下一章|前一章|后一章|前章|上章|下章|本章)"
)
# 首行章节标题：第X章 / 第X章：副标题
_LEADING_CHAPTER_TITLE = re.compile(
    r"^[\s　]*第[零〇一二三四五六七八九十百千万两0-9]+章"
    r"(?:\s*[：:\-—–]\s*|\s+)[^\n]{0,80}$"
    r"|^[\s　]*第[零〇一二三四五六七八九十百千万两0-9]+章[\s　]*$"
)


def strip_leading_chapter_title(content: str) -> str:
    """去掉正文开头的章节标题行，避免误伤合法标题。"""
    if not content:
        return content
    lines = content.split("\n")
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and _LEADING_CHAPTER_TITLE.match(lines[i].rstrip()):
        i += 1
        while i < len(lines) and not lines[i].strip():
            i += 1
        return "\n".join(lines[i:])
    return content


def find_chapter_meta_refs(content: str) -> list[dict[str, str]]:
    """检测正文叙述中的章号/章节元指称（不检测独立 title 字段）。

    命中示例：「第二十一章」「第21章」「上一章」「本章」。
    首行「第四十章：xxx」视为标题，不计入。
    """
    body = strip_leading_chapter_title(content or "")
    if not body.strip():
        return []

    hits: list[str] = []
    for m in _CHAPTER_NUM_META.finditer(body):
        hits.append(m.group(0))
    for m in _CHAPTER_REL_META.finditer(body):
        hits.append(m.group(0))

    if not hits:
        return []

    uniq = list(dict.fromkeys(hits))
    return [
        {
            "type": "chapter_meta",
            "severity": "error",
            "message": "正文出现章号/章节元指称，破坏沉浸感",
            "detail": "命中：" + "、".join(uniq[:12]),
        }
    ]


async def check_consistency(
    session: AsyncSession,
    novel: Novel,
    content: str,
    *,
    recent_tail: str = "",
) -> ConsistencyReport:
    bible = await bible_svc.list_bible(session, novel.id)
    bible_text = bible_svc.format_bible_text(
        bible["characters"], bible["world_settings"], bible["plot_threads"]
    )

    issues: list[ConsistencyIssue] = []
    # 规则层：禁止事项关键词
    for w in bible["world_settings"]:
        if w.do_not_violate:
            # 粗检：禁止条款中的「不得XXX」不直接匹配正文；留给 LLM
            pass
    for issue in bible_svc.match_alias_mentions(content, bible["characters"]):
        issues.append(ConsistencyIssue(**issue))
    for issue in find_chapter_meta_refs(content):
        issues.append(ConsistencyIssue(**issue))

    client = get_llm_client()
    prompt = render(
        "consistency.j2",
        story_bible=bible_text or "（空）",
        recent_tail=recent_tail[-2000:] if recent_tail else "（无）",
        content=content[:10000],
    )
    result = await client.chat(
        [{"role": "user", "content": prompt}],
        endpoint=client.summary_endpoint(),
        temperature=0.1,
        purpose="consistency",
    )
    await log_cost(
        session,
        purpose="consistency",
        provider=result.provider,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        novel_id=novel.id,
    )
    raw: dict[str, Any] = {}
    try:
        data = extract_json(result.text)
        raw = data if isinstance(data, dict) else {}
        for it in raw.get("issues") or []:
            issues.append(
                ConsistencyIssue(
                    type=it.get("type") or "other",
                    severity=it.get("severity") or "warning",
                    message=it.get("message") or "",
                    detail=it.get("detail"),
                )
            )
        ok = bool(raw.get("ok", len(issues) == 0))
    except Exception:  # noqa: BLE001
        ok = len(issues) == 0

    # 有 error 级别则 ok=False
    if any(i.severity == "error" for i in issues):
        ok = False
    elif issues and raw.get("ok") is False:
        ok = False

    return ConsistencyReport(ok=ok, issues=issues, raw=raw or None)


async def critic_revise(
    session: AsyncSession,
    novel: Novel,
    content: str,
    report: ConsistencyReport,
) -> tuple[str, ConsistencyReport]:
    """最多由调用方控制轮次；此处执行单轮修正。"""
    if report.ok or not report.issues:
        return content, report

    bible = await bible_svc.list_bible(session, novel.id)
    bible_text = bible_svc.format_bible_text(
        bible["characters"], bible["world_settings"], bible["plot_threads"]
    )
    prompt = render(
        "critic.j2",
        issues=[i.model_dump() for i in report.issues],
        story_bible=bible_text,
        content=content,
    )
    client = get_llm_client()
    result = await client.chat(
        [{"role": "user", "content": prompt}],
        endpoint=client.generation_endpoint(),
        temperature=0.4,
        max_tokens=8000,
        purpose="critic",
    )
    await log_cost(
        session,
        purpose="critic",
        provider=result.provider,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        novel_id=novel.id,
    )
    revised = result.text.strip()
    new_report = await check_consistency(session, novel, revised)
    new_report.critic_rounds = report.critic_rounds + 1
    return revised, new_report


async def run_critic_loop(
    session: AsyncSession,
    novel: Novel,
    content: str,
    *,
    recent_tail: str = "",
    max_rounds: int = 2,
) -> tuple[str, ConsistencyReport, ConsistencyReport]:
    """返回 (正文, 终检报告, 初检报告)。

    初检报告对应进入 Critic 前的草稿；若未改写，初检与终检相同。
    """
    report = await check_consistency(session, novel, content, recent_tail=recent_tail)
    report.critic_rounds = 0
    initial = report.model_copy(deep=True)
    rounds = 0
    while not report.ok and rounds < max_rounds:
        content, report = await critic_revise(session, novel, content, report)
        rounds = report.critic_rounds
        # 若仅剩 info，视为可接受
        if all(i.severity == "info" for i in report.issues):
            report.ok = True
            break
    return content, report, initial
