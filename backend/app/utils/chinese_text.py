"""中文文本处理：分章、字数、繁简、清洗、token 估算。"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

import chardet

try:
    import jieba
except ImportError:  # pragma: no cover
    jieba = None  # type: ignore

try:
    from opencc import OpenCC
except ImportError:  # pragma: no cover
    OpenCC = None  # type: ignore

try:
    import tiktoken
except ImportError:  # pragma: no cover
    tiktoken = None  # type: ignore

# ---- 分章正则（按优先级尝试）----
CHAPTER_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"(?m)^[ 　\t]*第[零〇一二三四五六七八九十百千万两0-9]+章[ 　\t]*[^\n]{0,40}$"
    ),
    re.compile(r"(?m)^[ 　\t]*Chapter\s+[0-9]+[^\n]{0,40}$", re.IGNORECASE),
    re.compile(r"(?m)^[ 　\t]*第[零〇一二三四五六七八九十百千万两0-9]+节[ 　\t]*[^\n]{0,40}$"),
    # 序章等须整行或后接空白副标题，避免「引子内容」误匹配
    re.compile(
        r"(?m)^[ 　\t]*(序章|楔子|引子|序言|前言|尾声|后记|番外)(?:[ 　\t]+[^\n]{0,40})?$"
    ),
    re.compile(r"(?m)^[ 　\t]*[0-9]{1,4}[、.．][ 　\t]*[^\n]{2,40}$"),
]

VOLUME_PATTERN = re.compile(
    r"(?m)^[ 　\t]*第[零〇一二三四五六七八九十百千万两0-9]+卷[ 　\t]*[^\n]{0,40}$"
)

_cc: Optional[object] = None
_enc = None


def _get_cc():
    global _cc
    if _cc is None and OpenCC is not None:
        _cc = OpenCC("t2s")
    return _cc


def _get_encoder():
    global _enc
    if _enc is None and tiktoken is not None:
        try:
            _enc = tiktoken.get_encoding("cl100k_base")
        except Exception:  # noqa: BLE001
            _enc = None
    return _enc


def detect_encoding(raw: bytes) -> str:
    result = chardet.detect(raw)
    enc = (result.get("encoding") or "utf-8").lower()
    if enc in ("gb2312", "gbk", "gb18030"):
        return "gb18030"
    if enc.startswith("utf-8"):
        return "utf-8"
    return enc


def decode_bytes(raw: bytes) -> str:
    enc = detect_encoding(raw)
    for candidate in (enc, "utf-8", "gb18030", "big5"):
        try:
            return raw.decode(candidate)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def to_simplified(text: str) -> str:
    cc = _get_cc()
    if cc is None:
        return text
    return cc.convert(text)  # type: ignore[attr-defined]


def clean_text(text: str) -> str:
    text = text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    text = unicodedata.normalize("NFKC", text)
    text = to_simplified(text)
    # 压缩多余空行
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def count_chars(text: str) -> int:
    """中文字数：去掉空白后的字符数。"""
    return len(re.sub(r"\s+", "", text))


def count_tokens(text: str) -> int:
    enc = _get_encoder()
    if enc is not None:
        try:
            return len(enc.encode(text))
        except Exception:  # noqa: BLE001
            pass
    # 中文兜底：约 1.5 token/字
    chars = count_chars(text)
    ascii_len = len(re.findall(r"[A-Za-z0-9]+", text))
    return int(chars * 1.5 + ascii_len)


_CN_DIGITS = "零一二三四五六七八九"


def int_to_chinese(n: int) -> str:
    """将正整数转为中文数字（覆盖常见章号 1–9999）。"""
    if n < 0:
        raise ValueError("n must be non-negative")
    if n < 10:
        return _CN_DIGITS[n]
    if n < 20:
        return "十" if n == 10 else f"十{_CN_DIGITS[n - 10]}"
    if n < 100:
        tens, ones = divmod(n, 10)
        return f"{_CN_DIGITS[tens]}十" + (_CN_DIGITS[ones] if ones else "")
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        if rest == 0:
            return f"{_CN_DIGITS[hundreds]}百"
        if rest < 10:
            return f"{_CN_DIGITS[hundreds]}百零{_CN_DIGITS[rest]}"
        return f"{_CN_DIGITS[hundreds]}百{int_to_chinese(rest)}"
    if n < 10000:
        thousands, rest = divmod(n, 1000)
        if rest == 0:
            return f"{_CN_DIGITS[thousands]}千"
        if rest < 100:
            return f"{_CN_DIGITS[thousands]}千零{int_to_chinese(rest)}"
        return f"{_CN_DIGITS[thousands]}千{int_to_chinese(rest)}"
    return str(n)


def extract_keywords(text: str, top_k: int = 20) -> list[str]:
    if jieba is None:
        # 简单按标点切
        parts = re.split(r"[\s，。！？、；：\"\"''（）\[\]【】]+", text)
        return [p for p in parts if 1 < len(p) <= 8][:top_k]
    words = jieba.lcut(text)
    freq: dict[str, int] = {}
    for w in words:
        if len(w) < 2 or re.fullmatch(r"[\W\d]+", w):
            continue
        freq[w] = freq.get(w, 0) + 1
    return [w for w, _ in sorted(freq.items(), key=lambda x: -x[1])[:top_k]]


@dataclass
class ParsedChapter:
    index: int
    title: str
    content: str
    volume: Optional[str] = None

    @property
    def char_count(self) -> int:
        return count_chars(self.content)


def _score_pattern(text: str, pattern: re.Pattern[str]) -> int:
    return len(pattern.findall(text))


def choose_chapter_pattern(text: str) -> Optional[re.Pattern[str]]:
    best: Optional[re.Pattern[str]] = None
    best_score = 0
    for p in CHAPTER_PATTERNS:
        score = _score_pattern(text, p)
        if score > best_score:
            best_score = score
            best = p
    return best if best_score >= 1 else None


def _collect_heading_matches(text: str, pattern: re.Pattern[str]) -> list[re.Match[str]]:
    return list(pattern.finditer(text))


def split_by_matches(text: str, matches: list[re.Match[str]]) -> list[ParsedChapter]:
    if not matches:
        return []
    # 去重：同一起始位置只留一处
    uniq: dict[int, re.Match[str]] = {}
    for m in matches:
        uniq.setdefault(m.start(), m)
    matches = [uniq[k] for k in sorted(uniq)]

    volumes = list(VOLUME_PATTERN.finditer(text))
    current_volume: Optional[str] = None
    vol_idx = 0

    chapters: list[ParsedChapter] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        while vol_idx < len(volumes) and volumes[vol_idx].start() <= start:
            current_volume = volumes[vol_idx].group(0).strip()
            vol_idx += 1
        title = m.group(0).strip()
        body = text[m.end() : end].strip()
        if not body and i == 0:
            continue
        chapters.append(
            ParsedChapter(
                index=len(chapters) + 1,
                title=title,
                content=body or title,
                volume=current_volume,
            )
        )
    return chapters


def split_by_pattern(text: str, pattern: re.Pattern[str]) -> list[ParsedChapter]:
    return split_by_matches(text, _collect_heading_matches(text, pattern))


def split_by_char_count(text: str, chunk_size: int = 3000) -> list[ParsedChapter]:
    """按字数兜底分割。"""
    cleaned = text.strip()
    if not cleaned:
        return []
    chapters: list[ParsedChapter] = []
    pos = 0
    idx = 1
    while pos < len(cleaned):
        end = min(pos + chunk_size, len(cleaned))
        # 尽量在段落边界切
        if end < len(cleaned):
            nl = cleaned.rfind("\n", pos + chunk_size // 2, end)
            if nl > pos:
                end = nl
        chunk = cleaned[pos:end].strip()
        if chunk:
            chapters.append(ParsedChapter(index=idx, title=f"第{idx}章", content=chunk))
            idx += 1
        pos = end if end > pos else pos + chunk_size
    return chapters


def parse_chapters(text: str) -> list[ParsedChapter]:
    text = clean_text(text)
    # 合并「序章/楔子」与「第X章」等标题，避免只识别一种
    primary = [
        CHAPTER_PATTERNS[0],  # 第X章
        CHAPTER_PATTERNS[3],  # 序章/楔子/…
        CHAPTER_PATTERNS[1],  # Chapter N
        CHAPTER_PATTERNS[2],  # 第X节
    ]
    merged: list[re.Match[str]] = []
    for p in primary:
        merged.extend(_collect_heading_matches(text, p))
    if len(merged) >= 2 or (len(merged) == 1 and len(text) > 50):
        chapters = split_by_matches(text, merged)
        if len(chapters) >= 1:
            return chapters

    pattern = choose_chapter_pattern(text)
    if pattern is not None:
        chapters = split_by_pattern(text, pattern)
        if len(chapters) >= 1:
            return chapters
    return split_by_char_count(text)


def parse_directory_import(files: list[tuple[str, str]]) -> list[ParsedChapter]:
    """目录结构导入：[(相对路径, 内容), ...]。
    路径如 volume1/001_标题.txt 或 第1章.txt。
    """
    sorted_files = sorted(files, key=lambda x: x[0])
    chapters: list[ParsedChapter] = []
    for path, content in sorted_files:
        content = clean_text(content)
        if not content:
            continue
        parts = path.replace("\\", "/").split("/")
        volume = parts[-2] if len(parts) >= 2 else None
        name = parts[-1]
        name = re.sub(r"\.(txt|md|text)$", "", name, flags=re.IGNORECASE)
        title = name
        chapters.append(
            ParsedChapter(
                index=len(chapters) + 1,
                title=title,
                content=content,
                volume=volume,
            )
        )
    return chapters
