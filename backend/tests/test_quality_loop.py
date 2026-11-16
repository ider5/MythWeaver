"""文风漂移、未回收伏笔、篇幅与章末钩子。"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.batch_generation import critic_gate_reason
from app.services.quality_loop import (
    assemble_signals,
    blocking_message,
    chapters_for_full_critic,
    end_hook_hint,
    length_hint,
    open_thread_views,
    spot_check_positions,
    style_drift_hints,
    thread_due_hints,
)


def _thread(**kwargs):
    base = {
        "id": 1,
        "title": "玉佩之谜",
        "thread_type": "伏笔",
        "status": "未回收",
        "introduced_chapter": 2,
        "resolved_chapter": None,
        "planned_resolve_chapter": None,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


LONG_SAMPLE = (
    "叶凡在青阳城外站了很久，看着城门上的灯一盏盏亮起来，心里却想起那块一直发热的玉佩。"
    "他没有进门，只把剑按在掌心，等风把城墙上的尘土吹干净。"
)


def test_style_drift_flags_short_sentences_against_samples():
    generated = "他进门。她回头。剑响了。风停了。灯灭了。人散了。门关上。"
    hints = style_drift_hints(generated * 4, [LONG_SAMPLE, LONG_SAMPLE])
    assert any(hint["id"] == "style:sentence" for hint in hints)
    assert all(hint["severity"] == "info" for hint in hints)
    assert all(hint["kind"] == "style" for hint in hints)


def test_style_drift_silent_without_samples_or_when_close():
    assert style_drift_hints(LONG_SAMPLE * 2, []) == []
    assert style_drift_hints("太短。", [LONG_SAMPLE]) == []
    close = style_drift_hints(LONG_SAMPLE + LONG_SAMPLE, [LONG_SAMPLE])
    assert close == []


def test_style_drift_flags_dialogue_and_person():
    sample = "「你来晚了。」苏婉说。「城门要关了。」叶凡应了一声。「我知道。」" * 6
    generated = "叶凡走进城门，看见灯火，把剑收回鞘中，没有说话，只是继续往前。" * 4
    dialogue = style_drift_hints(generated, [sample])
    assert any(hint["id"] == "style:dialogue" for hint in dialogue)

    first = "我推开门。我看见她。我没有说话。我把信放下。我转身离开。我知道不能回头。" * 3
    third = "他推开门。他看见她。他没有说话。他把信放下。他转身离开。他知道不能回头。" * 3
    person = style_drift_hints(third, [first])
    assert any(hint["id"] == "style:person" for hint in person)


def test_open_threads_skip_resolved_and_future_and_rank_due():
    threads = [
        _thread(id=1, title="远线", planned_resolve_chapter=20),
        _thread(id=2, title="临近", planned_resolve_chapter=6),
        _thread(id=3, title="到期", planned_resolve_chapter=5),
        _thread(id=4, title="逾期", planned_resolve_chapter=3),
        _thread(id=5, title="已收", status="已回收", planned_resolve_chapter=3),
        _thread(id=6, title="以后才出场", introduced_chapter=9, planned_resolve_chapter=12),
        _thread(id=7, title="未排期", planned_resolve_chapter=None),
    ]
    rows = open_thread_views(threads, 5)
    titles = [row["title"] for row in rows]
    assert titles[0] == "逾期"
    assert "到期" in titles
    assert "临近" in titles
    assert "远线" in titles
    assert "未排期" in titles
    assert "已收" not in titles
    assert "以后才出场" not in titles
    overdue = next(row for row in rows if row["title"] == "逾期")
    assert overdue["due"] == "overdue"
    assert "逾期" in overdue["note"]
    unscheduled = next(row for row in rows if row["title"] == "未排期")
    assert unscheduled["due"] is None
    assert "尚未安排回收" in unscheduled["note"]


def test_thread_due_hints_only_when_planned_chapter_is_near():
    threads = [
        _thread(id=1, title="远线", planned_resolve_chapter=30),
        _thread(id=2, title="逾期", planned_resolve_chapter=2),
    ]
    hints = thread_due_hints(threads, 8)
    assert len(hints) == 1
    assert hints[0]["severity"] == "warning"
    assert "逾期" in hints[0]["message"]
    approaching = thread_due_hints([_thread(planned_resolve_chapter=10)], 8)
    assert approaching[0]["severity"] == "info"
    assert approaching[0]["id"].endswith(":approaching")


def test_length_hint_uses_twenty_percent_band():
    target = 1000
    body = "叶" * 1000
    assert length_hint(body, target) is None
    assert length_hint("叶" * 800, target) is None
    assert length_hint("叶" * 1200, target) is None
    short = length_hint("叶" * 799, target)
    assert short is not None
    assert short["severity"] == "error"
    assert short["kind"] == "length"
    long = length_hint("叶" * 1201, target)
    assert long is not None and "长于" in long["message"]
    assert length_hint(body, 0) is None


def test_end_hook_requires_outline_words_in_the_ending():
    assert end_hook_hint("叶凡走进秘境，玉佩发光。", "") is None
    missing = end_hook_hint("叶凡走进秘境，玉佩发光。" * 20, "城门后站着苏婉")
    assert missing is not None
    assert missing["kind"] == "end_hook"
    assert missing["severity"] == "error"
    landed = "叶凡走到最后一级石阶。" * 10 + "城门后站着苏婉，她没有回头。"
    assert end_hook_hint(landed, "城门后站着苏婉") is None


def test_blocking_message_ignores_style_and_thread_warnings():
    signals = assemble_signals(
        chapter_index=8,
        content="他进门。她回头。剑响了。风停了。灯灭了。人散了。",
        references=[LONG_SAMPLE],
        threads=[_thread(planned_resolve_chapter=8)],
        target_chars=0,
        suspense_hook="",
        include_local_rules=False,
    )
    assert blocking_message(signals) is None
    assert any(hint["kind"] == "thread" for hint in signals["hints"])
    short = assemble_signals(
        chapter_index=1,
        content="太短。",
        references=[],
        threads=[],
        target_chars=1000,
        suspense_hook="苏婉站在城门",
        include_local_rules=False,
    )
    assert short["critical"] is True
    reason = blocking_message(short)
    assert reason is not None
    assert "短于" in reason


def test_spot_check_covers_ends_and_every_third():
    assert spot_check_positions(1) == {0}
    assert spot_check_positions(2) == {0, 1}
    assert spot_check_positions(4) == {0, 3}
    assert spot_check_positions(10) == {0, 3, 6, 9}
    assert chapters_for_full_critic(4, spot_check=False) == {0, 1, 2, 3}
    assert chapters_for_full_critic(4, spot_check=True) == {0, 3}


def test_critic_warnings_do_not_pause_batch():
    assert (
        critic_gate_reason(
            {
                "ok": False,
                "issues": [{"severity": "warning", "message": "口气偏硬"}],
            },
            run_critic=True,
        )
        is None
    )
    reason = critic_gate_reason(
        {
            "ok": False,
            "issues": [{"severity": "error", "message": "人物行为与设定冲突"}],
        },
        run_critic=True,
    )
    assert reason is not None
    assert "人物行为与设定冲突" in reason
    assert critic_gate_reason(None, run_critic=False) is None
