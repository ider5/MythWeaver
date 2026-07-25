"""大纲续写章号校正：后端强制从 start_from 起连续编号。"""

from app.services.outline import normalize_outline_items, rewrite_outline_title
from app.utils.chinese_text import int_to_chinese


def test_int_to_chinese_common_chapters():
    assert int_to_chinese(1) == "一"
    assert int_to_chinese(10) == "十"
    assert int_to_chinese(11) == "十一"
    assert int_to_chinese(31) == "三十一"
    assert int_to_chinese(40) == "四十"
    assert int_to_chinese(100) == "一百"
    assert int_to_chinese(101) == "一百零一"


def test_rewrite_replaces_wrong_chapter_prefix():
    assert rewrite_outline_title("第三十一章：秘境开启", 40) == "第四十章：秘境开启"
    assert rewrite_outline_title("第三十二章 玉佩异动", 41) == "第四十一章：玉佩异动"
    assert rewrite_outline_title("第31章 夜袭", 42) == "第四十二章：夜袭"
    assert rewrite_outline_title("秘境开启", 40) == "第四十章：秘境开启"
    assert rewrite_outline_title("", 40) == "第四十章"


def test_normalize_outline_items_from_39_starts_at_40():
    """已有 39 章 → 大纲条目从第 40 章起连续编号，不信任模型章号。"""
    raw = [
        {"order": 1, "title": "第三十一章：风云再起", "summary": "a", "key_points": ["x"]},
        {"order": 2, "title": "第三十二章：暗潮涌动", "summary": "b", "key_points": ["y"]},
        {"order": 3, "title": "第三十三章：破局", "summary": "c", "key_points": []},
    ]
    items = normalize_outline_items(raw, start_from_chapter=40)
    assert [i["title"] for i in items] == [
        "第四十章：风云再起",
        "第四十一章：暗潮涌动",
        "第四十二章：破局",
    ]
    assert [i["order"] for i in items] == [1, 2, 3]
    assert items[0]["summary"] == "a"
    assert items[0]["key_points"] == ["x"]
