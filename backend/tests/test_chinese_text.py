import pytest

from app.utils.chinese_text import (
    clean_text,
    count_chars,
    count_tokens,
    parse_chapters,
    parse_directory_import,
    split_by_char_count,
)


SAMPLE = """
《试炼之书》

第一章 初入江湖
张三走出山谷，望见远处的城镇。

第二章 夜遇奇人
李四自称散修，赠予张三一枚玉佩。

第三章 风云再起
城中忽然戒严，张三藏身客栈。
"""


def test_parse_chinese_chapters():
    chapters = parse_chapters(SAMPLE)
    assert len(chapters) >= 3
    assert "初入江湖" in chapters[0].title or chapters[0].title.startswith("第")
    assert chapters[0].char_count > 0


def test_chapter_variants():
    variants = [
        "第一章 开始\n正文A\n\n第二章 继续\n正文B\n",
        "第1章 开始\n正文A\n\n第2章 继续\n正文B\n",
        "Chapter 1 Start\nbodyA\n\nChapter 2 Next\nbodyB\n",
        "序章\n引子内容\n\n第一章 正题\n正文\n",
        "1、开端\n内容一\n\n2、发展\n内容二\n",
        "第一节 晨光\n内容\n\n第二节 黄昏\n内容\n",
    ]
    for text in variants:
        chs = parse_chapters(text)
        assert len(chs) >= 2, f"failed on: {text[:30]}"


def test_fallback_split():
    text = "甲" * 5000
    chs = split_by_char_count(text, chunk_size=2000)
    assert len(chs) >= 2


def test_directory_import():
    files = [
        ("vol1/001_开篇.txt", "很久很久以前。"),
        ("vol1/002_启程.txt", "少年踏上旅途。"),
    ]
    chs = parse_directory_import(files)
    assert len(chs) == 2
    assert chs[0].volume == "vol1"


def test_clean_and_count():
    text = clean_text("　測試\r\n\r\n\r\n內容  ")
    assert "测试" in text or "測試" in text or "内容" in text or "內容" in text
    assert count_chars("你好 world") >= 2
    assert count_tokens("你好世界") >= 4
