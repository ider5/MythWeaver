"""LangGraph Critic 回路单元测试（无真实 LLM）。"""

from __future__ import annotations

import pytest

from app.agents.critic_graph import run_critic_loop_langgraph
from app.schemas.generation import ConsistencyIssue, ConsistencyReport


@pytest.mark.asyncio
async def test_langgraph_critic_stops_when_ok():
    calls = {"check": 0, "revise": 0}

    async def check(content: str, *, recent_tail: str = "") -> ConsistencyReport:
        calls["check"] += 1
        return ConsistencyReport(ok=True, issues=[], critic_rounds=0)

    async def revise(content: str, report: ConsistencyReport) -> tuple[str, ConsistencyReport]:
        calls["revise"] += 1
        return content, report

    content, final, initial = await run_critic_loop_langgraph(
        content="正文",
        max_rounds=2,
        check_fn=check,
        revise_fn=revise,
    )
    assert content == "正文"
    assert final.ok is True
    assert initial.ok is True
    assert calls["check"] == 1
    assert calls["revise"] == 0


@pytest.mark.asyncio
async def test_langgraph_critic_revises_then_passes():
    calls = {"check": 0}

    async def check(content: str, *, recent_tail: str = "") -> ConsistencyReport:
        calls["check"] += 1
        if content.startswith("修好"):
            return ConsistencyReport(ok=True, issues=[], critic_rounds=0)
        return ConsistencyReport(
            ok=False,
            issues=[
                ConsistencyIssue(
                    type="plot",
                    severity="error",
                    message="矛盾",
                )
            ],
            critic_rounds=0,
        )

    async def revise(content: str, report: ConsistencyReport) -> tuple[str, ConsistencyReport]:
        new = await check("修好：" + content)
        new.critic_rounds = report.critic_rounds + 1
        return "修好：" + content, new

    content, final, initial = await run_critic_loop_langgraph(
        content="原稿",
        max_rounds=2,
        check_fn=check,
        revise_fn=revise,
    )
    assert content.startswith("修好")
    assert final.ok is True
    assert initial.ok is False
    assert final.critic_rounds >= 1
    assert calls["check"] >= 2


@pytest.mark.asyncio
async def test_langgraph_critic_respects_max_rounds_zero():
    async def check(content: str, *, recent_tail: str = "") -> ConsistencyReport:
        return ConsistencyReport(
            ok=False,
            issues=[ConsistencyIssue(type="x", severity="error", message="e")],
            critic_rounds=0,
        )

    async def revise(content: str, report: ConsistencyReport) -> tuple[str, ConsistencyReport]:
        raise AssertionError("max_rounds=0 不应修稿")

    content, final, _ = await run_critic_loop_langgraph(
        content="x",
        max_rounds=0,
        check_fn=check,
        revise_fn=revise,
    )
    assert content == "x"
    assert final.ok is False
