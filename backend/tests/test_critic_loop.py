"""Critic 回路：跳过整章重写时不得空转死循环。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.config import get_settings
from app.schemas.generation import ConsistencyIssue, ConsistencyReport
from app.services import consistency as cons_mod
from app.services.consistency import critic_revise, run_critic_loop


@pytest.mark.asyncio
async def test_critic_skip_rewrite_does_not_spin(monkeypatch):
    """目标短章却超写过阈值时，critic_revise 跳过重写且不得反复调用。"""
    monkeypatch.setenv("CHAPTER_SEGMENT_THRESHOLD", "10")
    get_settings.cache_clear()
    try:
        calls = {"n": 0}
        real_revise = critic_revise

        async def wrapped(session, novel, content, report):
            calls["n"] += 1
            if calls["n"] > 5:
                raise AssertionError("critic_revise 空转死循环")
            return await real_revise(session, novel, content, report)

        async def fake_check(session, novel, content, *, recent_tail=""):
            return ConsistencyReport(
                ok=False,
                issues=[
                    ConsistencyIssue(
                        type="chapter_meta",
                        severity="error",
                        message="正文出现章号元指称",
                    )
                ],
                critic_rounds=0,
            )

        monkeypatch.setattr(cons_mod, "check_consistency", fake_check)
        monkeypatch.setattr(cons_mod, "critic_revise", wrapped)

        content = "叶凡踏入秘境。" + ("剑光一闪。" * 20)
        assert cons_mod.count_chars(content) > get_settings().chapter_segment_threshold

        revised, report, _initial = await run_critic_loop(
            MagicMock(),
            MagicMock(),
            content,
            max_rounds=2,
        )
        assert calls["n"] == 1
        assert revised == content
        assert report.critic_rounds == 0
    finally:
        get_settings.cache_clear()
