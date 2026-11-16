"""Agent 运行时（LangGraph 等）适配层。"""

from __future__ import annotations

from app.agents.critic_graph import run_critic_loop_langgraph

__all__ = ["run_critic_loop_langgraph"]
