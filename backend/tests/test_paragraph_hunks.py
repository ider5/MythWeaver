"""修稿按段采用：对齐、整章采用、丢掉某一段。"""

from __future__ import annotations

import pytest

from app.services.paragraph_hunks import ParagraphHunkError, merge_paragraphs, paragraph_hunks


def test_identical_paragraphs_have_no_hunks():
    text = "甲段。\n乙段。"
    assert paragraph_hunks(text, text + "\n") == []
    assert merge_paragraphs(text, text + "\n", {}) == text + "\n"


def test_accept_all_keeps_revised_bytes():
    base = "甲段。\r\n乙段要改。\r\n"
    revised = "甲段。\r\n乙段已改。\r\n"
    hunks = paragraph_hunks(base, revised)
    assert [item["op"] for item in hunks] == ["replace"]
    assert merge_paragraphs(base, revised, None) == revised
    assert merge_paragraphs(base, revised, {hunks[0]["id"]: True}) == revised


def test_drop_all_keeps_base_bytes():
    base = "甲。\n乙要删。\n丙。"
    revised = "甲。\n丙。"
    hunks = paragraph_hunks(base, revised)
    assert [item["op"] for item in hunks] == ["delete"]
    dropped = {hunks[0]["id"]: False}
    assert merge_paragraphs(base, revised, dropped) == base


def test_mixed_replace_insert_and_delete():
    base = "甲段保持。\n乙段要改。\n丙段要删。\n丁段保持。"
    revised = "甲段保持。\n乙段已改。\n丁段保持。\n戊段新增。"
    hunks = paragraph_hunks(base, revised)
    by_op = {item["op"]: item for item in hunks}
    assert set(by_op) == {"replace", "delete", "insert"}
    assert by_op["replace"]["before"] == "乙段要改。"
    assert by_op["replace"]["after"] == "乙段已改。"
    assert by_op["insert"]["after"] == "戊段新增。"

    decisions = {
        by_op["replace"]["id"]: True,
        by_op["delete"]["id"]: False,
        by_op["insert"]["id"]: False,
    }
    assert merge_paragraphs(base, revised, decisions) == "甲段保持。\n乙段已改。\n丙段要删。\n丁段保持。"


def test_blank_line_paragraphs_and_unknown_id():
    base = "甲段。\n\n乙段要改。\n\n丙段。"
    revised = "甲段。\n\n乙段已改。\n\n丙段。\n\n丁段新增。"
    hunks = paragraph_hunks(base, revised)
    assert [item["op"] for item in hunks] == ["replace", "insert"]
    decisions = {hunks[0]["id"]: False, hunks[1]["id"]: True}
    assert merge_paragraphs(base, revised, decisions) == "甲段。\n\n乙段要改。\n\n丙段。\n\n丁段新增。"
    with pytest.raises(ParagraphHunkError):
        merge_paragraphs(base, revised, {"h99": False})
