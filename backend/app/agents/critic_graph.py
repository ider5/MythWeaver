"""LangGraph 编排的 Critic 回路（校验 → 条件修稿）。

与 `services.consistency.run_critic_loop` 语义对齐，供特性开关切换。
LLM / DB 仍通过现有 check / revise 调用注入，便于单测 mock。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from app.schemas.generation import ConsistencyReport
from app.services.consistency import needs_critic_rewrite

CheckFn = Callable[..., Awaitable[ConsistencyReport]]
ReviseFn = Callable[..., Awaitable[tuple[str, ConsistencyReport]]]


class CriticState(TypedDict, total=False):
    content: str
    recent_tail: str
    max_rounds: int
    round: int
    report: ConsistencyReport
    initial_report: ConsistencyReport
    skipped: bool


def build_critic_graph(
    *,
    check_fn: CheckFn,
    revise_fn: ReviseFn,
) -> Any:
    """构建可编译的 Critic StateGraph。"""

    async def check_node(state: CriticState) -> dict[str, Any]:
        report = await check_fn(state["content"], recent_tail=state.get("recent_tail") or "")
        report.critic_rounds = int(state.get("round") or 0)
        out: dict[str, Any] = {"report": report}
        if state.get("initial_report") is None:
            out["initial_report"] = report.model_copy(deep=True)
            out["round"] = 0
            report.critic_rounds = 0
        return out

    async def revise_node(state: CriticState) -> dict[str, Any]:
        content, report = await revise_fn(state["content"], state["report"])
        # 跳过整章重写时 content 不变 → 标 skipped，下一跳结束
        skipped = content == state["content"]
        return {
            "content": content,
            "report": report,
            "round": int(report.critic_rounds),
            "skipped": skipped,
        }

    def after_check(state: CriticState) -> Literal["revise", "done"]:
        report = state.get("report")
        if report is None:
            return "done"
        max_rounds = int(state.get("max_rounds") or 0)
        round_n = int(state.get("round") or 0)
        if max_rounds <= 0:
            return "done"
        if round_n >= max_rounds:
            return "done"
        if not needs_critic_rewrite(report):
            return "done"
        if all(i.severity == "info" for i in (report.issues or [])):
            return "done"
        return "revise"

    def after_revise(state: CriticState) -> Literal["check", "done"]:
        if state.get("skipped"):
            return "done"
        report = state.get("report")
        if report is None:
            return "done"
        if all(i.severity == "info" for i in (report.issues or [])):
            if report is not None:
                report.ok = True
            return "done"
        max_rounds = int(state.get("max_rounds") or 0)
        if int(state.get("round") or 0) >= max_rounds:
            return "done"
        return "check"

    g: StateGraph = StateGraph(CriticState)
    g.add_node("check", check_node)
    g.add_node("revise", revise_node)
    g.add_edge(START, "check")
    g.add_conditional_edges("check", after_check, {"revise": "revise", "done": END})
    g.add_conditional_edges("revise", after_revise, {"check": "check", "done": END})
    return g.compile()


async def run_critic_loop_langgraph(
    *,
    content: str,
    recent_tail: str = "",
    max_rounds: int = 2,
    check_fn: CheckFn,
    revise_fn: ReviseFn,
) -> tuple[str, ConsistencyReport, ConsistencyReport]:
    """返回 (正文, 终检, 初检)，语义对齐 legacy `run_critic_loop`。"""
    app = build_critic_graph(check_fn=check_fn, revise_fn=revise_fn)
    final: CriticState = await app.ainvoke(
        {
            "content": content,
            "recent_tail": recent_tail,
            "max_rounds": max(0, max_rounds),
            "round": 0,
        }
    )
    report = final["report"]
    initial = final.get("initial_report") or report.model_copy(deep=True)
    return final["content"], report, initial
