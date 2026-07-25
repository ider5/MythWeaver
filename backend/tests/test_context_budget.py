import pytest

from app.services.context_builder import BUDGET, BuiltContext
from app.utils.chinese_text import count_tokens


def test_budget_constants():
    assert BUDGET["recent"] == 8000
    assert BUDGET["bible"] == 2500
    # 不可裁剪优先级：recent + bible 最大
    assert BUDGET["recent"] + BUDGET["bible"] > BUDGET["rag"]


def test_trim_priority_logic():
    """模拟裁剪优先级：卷摘要 → RAG → 章摘要。"""
    trimmed: list[str] = []
    include_vol = True
    rag_n = 8
    chap_n = 5

    def used_tokens(vol: bool, rag: int, chap: int, style_len: int) -> int:
        return (500 if vol else 0) + rag * 200 + chap * 300 + style_len

    style_len = 800
    # 假设预算很紧
    flexible = 1500
    while used_tokens(include_vol, rag_n, chap_n, style_len) > flexible:
        if include_vol:
            include_vol = False
            trimmed.append("volume_summaries")
            continue
        if rag_n > 3:
            rag_n -= 1
            trimmed.append("rag")
            continue
        if chap_n > 2:
            chap_n -= 1
            trimmed.append("chapter_summaries")
            continue
        style_len = max(200, style_len // 2)
        trimmed.append("style")
        break

    assert trimmed[0] == "volume_summaries"
    assert "rag" in trimmed
    assert chap_n >= 2


def test_built_context_dataclass():
    ctx = BuiltContext(recent_chapters="最近两章", story_bible="人物")
    assert count_tokens(ctx.recent_chapters) > 0
