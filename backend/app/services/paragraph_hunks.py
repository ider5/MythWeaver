"""把两版正文按段对齐，再按段采用或保留原文。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Mapping


class ParagraphHunkError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


@dataclass
class _Unit:
    kind: str
    before: str
    after: str
    hunk_id: str | None = None


def _normalized(text: str) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n")


def uses_blank_lines(text: str) -> bool:
    return bool(re.search(r"\n[ \t]*\n", _normalized(text)))


def split_paragraphs(text: str) -> list[str]:
    """空行分段；没有空行时，每个非空行是一段。"""
    normalized = _normalized(text)
    if not normalized.strip():
        return []
    if uses_blank_lines(normalized):
        parts = re.split(r"\n[ \t]*\n", normalized)
    else:
        parts = normalized.split("\n")
    return [part.strip("\n") for part in parts if part.strip()]


def _align(base: str, revised: str) -> list[_Unit]:
    base_parts = split_paragraphs(base)
    revised_parts = split_paragraphs(revised)
    matcher = SequenceMatcher(
        a=[part.strip() for part in base_parts],
        b=[part.strip() for part in revised_parts],
        autojunk=False,
    )
    units: list[_Unit] = []
    seq = 0

    def add_change(kind: str, before: str, after: str) -> None:
        nonlocal seq
        seq += 1
        units.append(_Unit(kind=kind, before=before, after=after, hunk_id=f"h{seq}"))

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                units.append(
                    _Unit(
                        kind="same",
                        before=base_parts[i1 + offset],
                        after=revised_parts[j1 + offset],
                    )
                )
            continue
        if tag == "replace":
            left = base_parts[i1:i2]
            right = revised_parts[j1:j2]
            paired = min(len(left), len(right))
            for index in range(paired):
                if left[index].strip() == right[index].strip():
                    units.append(_Unit(kind="same", before=left[index], after=right[index]))
                else:
                    add_change("replace", left[index], right[index])
            for part in left[paired:]:
                add_change("delete", part, "")
            for part in right[paired:]:
                add_change("insert", "", part)
            continue
        if tag == "delete":
            for part in base_parts[i1:i2]:
                add_change("delete", part, "")
            continue
        for part in revised_parts[j1:j2]:
            add_change("insert", "", part)
    return units


def paragraph_hunks(base: str, revised: str) -> list[dict[str, str]]:
    """只返回有改动的段。op 为 replace、insert 或 delete。"""
    return [
        {
            "id": unit.hunk_id or "",
            "op": unit.kind,
            "before": unit.before,
            "after": unit.after,
        }
        for unit in _align(base, revised)
        if unit.hunk_id
    ]


def merge_paragraphs(base: str, revised: str, decisions: Mapping[str, bool] | None) -> str:
    """decisions 为 None，或每一段都采用时，原样返回修订稿。

    缺省的段落 id 视为采用。全部不采用时原样返回原文。
    """
    if decisions is None:
        return revised
    units = _align(base, revised)
    change_ids = [unit.hunk_id for unit in units if unit.hunk_id]
    known = set(change_ids)
    unknown = [key for key in decisions if key not in known]
    if unknown:
        raise ParagraphHunkError("包含未知的段落")
    accepts = {hunk_id: bool(decisions.get(hunk_id, True)) for hunk_id in change_ids}
    if not change_ids or all(accepts.values()):
        return revised
    if not any(accepts.values()):
        return base
    separator = "\n\n" if uses_blank_lines(base) or uses_blank_lines(revised) else "\n"
    parts: list[str] = []
    for unit in units:
        hunk_id = unit.hunk_id or ""
        if unit.kind == "same":
            parts.append(unit.before)
        elif unit.kind == "replace":
            parts.append(unit.after if accepts[hunk_id] else unit.before)
        elif unit.kind == "insert" and accepts[hunk_id]:
            parts.append(unit.after)
        elif unit.kind == "delete" and not accepts[hunk_id]:
            parts.append(unit.before)
    return separator.join(parts)
