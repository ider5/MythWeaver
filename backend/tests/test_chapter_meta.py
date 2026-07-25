"""章号元指称检测：正文禁止「第X章」式结构引用，标题行不误伤。"""

from app.services.consistency import find_chapter_meta_refs, strip_leading_chapter_title


def test_detect_chinese_chapter_number():
    text = "他想起第二十一章那个细节，心头一紧。"
    issues = find_chapter_meta_refs(text)
    assert len(issues) == 1
    assert issues[0]["type"] == "chapter_meta"
    assert issues[0]["severity"] == "error"
    assert "第二十一章" in (issues[0].get("detail") or "")


def test_detect_arabic_chapter_number():
    issues = find_chapter_meta_refs("如同第21章发生的事再次上演。")
    assert issues and "第21章" in (issues[0].get("detail") or "")


def test_detect_relative_chapter_refs():
    for phrase in ("上一章", "下一章", "下章", "本章", "前一章"):
        issues = find_chapter_meta_refs(f"正如{phrase}所说，他早已布好局。")
        assert issues, f"should detect: {phrase}"
        assert phrase in (issues[0].get("detail") or "")


def test_title_line_not_flagged():
    content = "第四十章：秘境开启\n\n叶凡踏入青阳秘境，玉佩骤然发光。"
    assert strip_leading_chapter_title(content).startswith("叶凡")
    assert find_chapter_meta_refs(content) == []


def test_title_only_content_ok():
    assert find_chapter_meta_refs("第四十章：秘境开启") == []
    assert find_chapter_meta_refs("第四十章") == []


def test_title_plus_meta_in_body_flagged():
    content = "第四十章：秘境开启\n\n他想起第二十一章那个细节。"
    issues = find_chapter_meta_refs(content)
    assert issues
    assert "第二十一章" in (issues[0].get("detail") or "")


def test_clean_narrative_ok():
    text = "他想起玉佩发光的那一夜，城门戒严，李四失踪。"
    assert find_chapter_meta_refs(text) == []


def test_empty_content():
    assert find_chapter_meta_refs("") == []
    assert find_chapter_meta_refs("   \n  ") == []
