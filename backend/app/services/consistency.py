"""一致性校验 + Critic 自检回路。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.client import get_llm_client
from app.llm.cost_tracker import log_cost
from app.llm.prompts import render
from app.models import Character, Novel
from app.schemas.generation import ConsistencyIssue, ConsistencyReport
from app.services import story_bible as bible_svc
from app.utils.json_extract import extract_json


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
) -> tuple[str, ConsistencyReport]:
    report = await check_consistency(session, novel, content, recent_tail=recent_tail)
    report.critic_rounds = 0
    rounds = 0
    while not report.ok and rounds < max_rounds:
        content, report = await critic_revise(session, novel, content, report)
        rounds = report.critic_rounds
        # 若仅剩 info，视为可接受
        if all(i.severity == "info" for i in report.issues):
            report.ok = True
            break
    return content, report
