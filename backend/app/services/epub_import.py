"""把 EPUB 2/3 拆成章节，供原稿导入。只用标准库。"""

from __future__ import annotations

import io
import posixpath
import re
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import unquote
from xml.etree import ElementTree as ET

from app.utils.chinese_text import (
    CHAPTER_PATTERNS,
    VOLUME_PATTERN,
    ParsedChapter,
    clean_text,
    count_chars,
)

_TEXT_EXT = {".txt", ".md", ".text", ".markdown"}
_HTML_TYPES = {
    "application/xhtml+xml",
    "text/html",
    "application/html+xml",
    "application/xml",
    "text/xml",
}
_MAX_DECLARED = 64 * 1024 * 1024
_MAX_FILE = 8 * 1024 * 1024
_MAX_READ = 32 * 1024 * 1024
_MAX_CHAPTERS = 5000
_HEADING_PATTERNS = CHAPTER_PATTERNS[:4]
_SKIP_TITLE = re.compile(
    r"^(cover|toc|nav|contents|copyright|title[\s-]?page|目录|封面|扉页|版权信息|版权|制作信息)$",
    re.IGNORECASE,
)
_CHAPTER_LABEL = re.compile(
    r"第[零〇一二三四五六七八九十百千万两0-9０-９]+[章节回話话]"
    r"|[Cc]hapter\s+\d+"
    r"|(?:^|\s)(序章|楔子|引子|序言|前言|尾声|后记|番外)(?:\s|$)"
)
_VOLUME_LINE = re.compile(
    r"^[ 　\t]*(?:"
    r"第[零〇一二三四五六七八九十百千万两0-9０-９]+[卷部册]"
    r"|卷[零〇一二三四五六七八九十百千万两0-9０-９]+"
    r"|[Vv]ol(?:ume)?\.?\s*\d+"
    r"|[Bb]ook\s+\d+"
    r"|[Pp]art\s+\d+"
    r"|上部|下部|前传|后传"
    r")(?:[ 　\t]+\S.{0,30})?$"
)
_BLOCK_TAGS = {
    "p",
    "div",
    "li",
    "blockquote",
    "tr",
    "section",
    "article",
    "pre",
    "table",
    "header",
    "footer",
    "body",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
}
_SKIP_TAGS = {"script", "style", "svg", "math"}


class EpubImportError(ValueError):
    """EPUB 无法作为原稿导入。"""


@dataclass
class EpubBook:
    title: str
    author: str | None
    chapters: list[ParsedChapter]


def is_epub_upload(raw: bytes, filename: str | None) -> bool:
    """文件名或 zip 内的 mimetype 表明这是一本 EPUB。txt/md 永不走这条路径。"""
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    if name.endswith(".epub"):
        return True
    suffix = name[name.rfind(".") :] if "." in name else ""
    if suffix in _TEXT_EXT:
        return False
    if not raw.startswith(b"PK"):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            try:
                mime = zf.read("mimetype")
            except KeyError:
                return False
    except zipfile.BadZipFile:
        return False
    return mime.strip() == b"application/epub+zip"


def parse_epub(raw: bytes) -> EpubBook:
    """按阅读顺序抽出章节。嵌套目录里非章标题的上层记为卷。"""
    if not raw:
        raise EpubImportError("EPUB 是空文件")
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise EpubImportError("这不是有效的 EPUB 文件") from exc

    with zf:
        if sum(info.file_size for info in zf.infolist()) > _MAX_DECLARED:
            raise EpubImportError("EPUB 过大，无法导入")
        index = {name.replace("\\", "/").lower(): name for name in zf.namelist()}
        encrypted = any(name.endswith("encryption.xml") for name in index)
        budget = [0]
        opf_path = _opf_path(zf, index)
        opf_dir = posixpath.dirname(opf_path)
        root = _xml_root(_read_zip(zf, index, opf_path, budget))
        book_title, author = _metadata(root)
        items = _manifest(root)
        spine = _spine(root, items)
        toc = _toc_map(zf, index, opf_dir, items, budget)
        docs = _spine_docs(zf, index, opf_dir, spine, budget)
        primary = [doc for doc in docs if doc["linear"]]
        chapters = _chapters_from_docs(primary, toc)
        if not chapters and len(docs) != len(primary):
            chapters = _chapters_from_docs(docs, toc)
        if not chapters:
            if encrypted:
                raise EpubImportError("这本 EPUB 已加密，无法导入正文")
            raise EpubImportError("EPUB 里没有可导入的章节")
        if len(chapters) > _MAX_CHAPTERS:
            raise EpubImportError("章节过多，无法导入")
        for i, chapter in enumerate(chapters, start=1):
            chapter.index = i
        author_name = _clip(clean_text(author), 128) if author else ""
        return EpubBook(
            title=_clip(clean_text(book_title), 256),
            author=author_name or None,
            chapters=chapters,
        )


def _chapters_from_docs(docs: list[dict], toc: dict[str, tuple[str, str | None]]) -> list[ParsedChapter]:
    chapters: list[ParsedChapter] = []
    current_volume: str | None = None
    seen: set[str] = set()
    for doc in docs:
        path = doc["path"]
        if path in seen:
            continue
        seen.add(path)
        blocks, html_title = _html_blocks(doc["html"])
        in_toc = path in toc
        toc_title, toc_volume = toc.get(path, ("", None))
        if in_toc:
            current_volume = toc_volume
        many = _split_blocks(blocks)
        if many:
            last_volume = current_volume
            for title, body, vol in many:
                if vol:
                    last_volume = vol
                use_vol = vol or (toc_volume if in_toc else current_volume)
                _append_chapter(chapters, title, body, use_vol)
            current_volume = last_volume
            continue
        title = _pick_title(toc_title if in_toc else "", html_title, len(chapters) + 1)
        body = _plain_body(blocks, title)
        if _is_volume_heading_line(title) and count_chars(body) < 30:
            current_volume = _clip(title, 128) or current_volume
            continue
        volume = toc_volume if in_toc else current_volume
        if volume and title == volume and count_chars(body) < 30:
            current_volume = volume
            continue
        if _should_skip(title, body):
            continue
        _append_chapter(chapters, title, body, volume)
    return chapters


def _append_chapter(
    chapters: list[ParsedChapter],
    title: str,
    body: str,
    volume: str | None,
) -> None:
    cleaned_title = _clip(clean_text(title), 256) or f"第{len(chapters) + 1}章"
    cleaned_body = clean_text(body) or cleaned_title
    if _should_skip(cleaned_title, cleaned_body):
        return
    vol = _clip(clean_text(volume), 128) if volume else ""
    chapters.append(
        ParsedChapter(
            index=len(chapters) + 1,
            title=cleaned_title,
            content=cleaned_body,
            volume=vol or None,
        )
    )


def _spine_docs(
    zf: zipfile.ZipFile,
    index: dict[str, str],
    opf_dir: str,
    spine: list[tuple[_ManifestItem, bool]],
    budget: list[int],
) -> list[dict]:
    docs: list[dict] = []
    for item, linear in spine:
        if "nav" in item.props or "cover-image" in item.props:
            continue
        if "ncx" in item.media or "dtbncx" in item.media:
            continue
        path = _resolve(opf_dir, item.href)
        if not path or not _is_html(item, path):
            continue
        try:
            raw = _read_zip(zf, index, path, budget)
        except EpubImportError as exc:
            if "过大" in str(exc):
                raise
            continue
        docs.append({"path": path, "linear": linear, "html": _decode(raw)})
    return docs


def _toc_map(
    zf: zipfile.ZipFile,
    index: dict[str, str],
    opf_dir: str,
    items: dict[str, _ManifestItem],
    budget: list[int],
) -> dict[str, tuple[str, str | None]]:
    toc: dict[str, tuple[str, str | None]] = {}
    ncx = next((item for item in items.values() if "dtbncx" in item.media or item.media.endswith("ncx")), None)
    nav = next((item for item in items.values() if "nav" in item.props and _is_html(item, item.href)), None)
    if ncx is not None:
        path = _resolve(opf_dir, ncx.href)
        if path:
            try:
                root = _xml_root(_read_zip(zf, index, path, budget))
            except EpubImportError as exc:
                if "过大" in str(exc):
                    raise
                root = None
            if root is not None:
                _merge_toc(toc, _ncx_entries(root), posixpath.dirname(path))
    if nav is not None:
        path = _resolve(opf_dir, nav.href)
        if path:
            try:
                html = _decode(_read_zip(zf, index, path, budget))
            except EpubImportError as exc:
                if "过大" in str(exc):
                    raise
                html = ""
            if html:
                _merge_toc(toc, _nav_entries(html), posixpath.dirname(path))
    return toc


def _merge_toc(
    toc: dict[str, tuple[str, str | None]],
    entries: list[tuple[str, str, str | None]],
    base_dir: str,
) -> None:
    for href, title, volume in entries:
        key = _resolve(base_dir, href)
        if not key:
            continue
        _remember(toc, key, title, volume)


def _remember(toc: dict[str, tuple[str, str | None]], key: str, title: str, volume: str | None) -> None:
    title = re.sub(r"\s+", " ", title or "").strip()
    volume = re.sub(r"\s+", " ", volume).strip() if volume else None
    prev = toc.get(key)
    if prev is None:
        toc[key] = (title, volume)
        return
    old_title, old_vol = prev
    if title and (_is_chapter_label(title) or not _is_chapter_label(old_title)):
        chosen = title
    else:
        chosen = old_title or title
    toc[key] = (chosen, volume or old_vol)


def _ncx_entries(root: ET.Element) -> list[tuple[str, str, str | None]]:
    nav_map = next((el for el in root.iter() if _ln(el.tag) == "navMap"), None)
    if nav_map is None:
        return []
    entries: list[tuple[str, str, str | None]] = []

    def walk(points: list[ET.Element], volume: str | None) -> None:
        for point in points:
            label = _ncx_label(point)
            content = _child(point, "content")
            src = _attr(content, "src") if content is not None else ""
            kids = _children(point, "navPoint")
            is_volume = bool(kids) and bool(label) and not _is_chapter_label(label)
            next_volume = label if is_volume else volume
            if src:
                entries.append((src, label, next_volume if is_volume else volume))
            if kids:
                walk(kids, next_volume)

    walk(_children(nav_map, "navPoint"), None)
    return entries


def _ncx_label(point: ET.Element) -> str:
    label = _child(point, "navLabel")
    if label is None:
        return ""
    node = _child(label, "text")
    if node is None:
        return ""
    return re.sub(r"\s+", " ", "".join(node.itertext())).strip()


def _nav_entries(html: str) -> list[tuple[str, str, str | None]]:
    parser = _NavToc()
    parser.feed(_prepare_html(html))
    parser.close()
    return parser.entries


class _NavToc(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.nav_is_toc: list[bool] = []
        self.li_stack: list[dict] = []
        self.volume_stack: list[str] = []
        self.entries: list[tuple[str, str, str | None]] = []
        self._anchor: dict | None = None

    @property
    def in_toc(self) -> bool:
        return any(self.nav_is_toc)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = _tag(tag)
        ad = {k.lower(): (v or "") for k, v in attrs}
        if tag == "nav":
            kind = (ad.get("epub:type") or ad.get("type") or "").lower()
            self.nav_is_toc.append("toc" in kind.split())
            return
        if not self.in_toc:
            return
        if tag in {"ol", "ul"}:
            if self.li_stack and not self.li_stack[-1].get("pushed"):
                parent = self.li_stack[-1]
                title = (parent.get("title") or "").strip()
                if title and not _is_chapter_label(title):
                    self.volume_stack.append(title)
                    parent["pushed"] = True
                    parent["is_volume"] = True
            return
        if tag == "li":
            self.li_stack.append({"href": None, "title": "", "is_volume": False, "pushed": False})
            return
        if tag == "a":
            self._anchor = {"href": ad.get("href") or "", "buf": []}

    def handle_endtag(self, tag: str) -> None:
        tag = _tag(tag)
        if tag == "a" and self._anchor is not None:
            title = re.sub(r"\s+", " ", "".join(self._anchor["buf"])).strip()
            href = self._anchor["href"]
            if self.in_toc and self.li_stack and not self.li_stack[-1]["href"]:
                self.li_stack[-1]["href"] = href
                self.li_stack[-1]["title"] = title
            self._anchor = None
            return
        if tag == "nav":
            if self.nav_is_toc:
                self.nav_is_toc.pop()
            return
        if tag == "li" and self.in_toc and self.li_stack:
            item = self.li_stack.pop()
            href = item.get("href") or ""
            title = (item.get("title") or "").strip()
            if item.get("is_volume"):
                volume = title or None
            else:
                volume = self.volume_stack[-1] if self.volume_stack else None
            if item.get("pushed") and self.volume_stack:
                self.volume_stack.pop()
            if href and title:
                self.entries.append((href, title, volume))

    def handle_data(self, data: str) -> None:
        if self._anchor is not None:
            self._anchor["buf"].append(data)


def _split_blocks(blocks: list[tuple[str, str]]) -> list[tuple[str, str, str | None]] | None:
    marks: list[tuple[int, str, str]] = []
    for i, (kind, text) in enumerate(blocks):
        if _is_chapter_heading_line(text):
            marks.append((i, "ch", text))
        elif _is_volume_heading_line(text):
            marks.append((i, "vol", text))
    if sum(1 for _, kind, _ in marks if kind == "ch") < 2:
        return None
    current: str | None = None
    chapters: list[tuple[str, str, str | None]] = []
    first = marks[0][0]
    preface = _join_between(blocks, 0, first)
    if count_chars(preface) >= 30:
        chapters.append(("前言", preface, None))
    for idx, (pos, kind, text) in enumerate(marks):
        nxt = marks[idx + 1][0] if idx + 1 < len(marks) else len(blocks)
        body = _join_between(blocks, pos + 1, nxt)
        if kind == "vol":
            current = text
            if count_chars(body) >= 30:
                chapters.append((text, body, current))
            continue
        chapters.append((text, body, current))
    return chapters


def _join_between(blocks: list[tuple[str, str]], start: int, end: int) -> str:
    parts: list[str] = []
    for _kind, text in blocks[start:end]:
        if _is_chapter_heading_line(text) or _is_volume_heading_line(text):
            continue
        if text.strip():
            parts.append(text.strip())
    return "\n\n".join(parts).strip()


def _plain_body(blocks: list[tuple[str, str]], title: str) -> str:
    parts = [text.strip() for kind, text in blocks if kind == "p" and text.strip()]
    if not parts:
        parts = [
            text.strip()
            for kind, text in blocks
            if kind.startswith("h") and text.strip() and text.strip() != title.strip()
        ]
    return _strip_leading_title(title, "\n\n".join(parts).strip())


def _html_blocks(html: str) -> tuple[list[tuple[str, str]], str]:
    parser = _HtmlDoc()
    parser.feed(_prepare_html(html))
    parser.close()
    title = ""
    for level in ("h1", "h2", "h3"):
        for kind, text in parser.blocks:
            if kind == level and text.strip():
                title = text.strip()
                break
        if title:
            break
    if not title:
        title = re.sub(r"\s+", " ", parser.doc_title).strip()
    return parser.blocks, title


class _HtmlDoc(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str]] = []
        self.doc_title = ""
        self._skip = 0
        self._in_title = False
        self._heading: str | None = None
        self._buf: list[str] = []

    def close(self) -> None:
        super().close()
        self._flush()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = _tag(tag)
        if tag in _SKIP_TAGS:
            self._skip += 1
            return
        if self._skip:
            return
        if tag == "title":
            self._in_title = True
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._flush()
            self._heading = tag
            return
        if tag == "br":
            self._buf.append("\n")
            return
        if tag in _BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        tag = _tag(tag)
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag == "title":
            self._in_title = False
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._flush(heading=self._heading or tag)
            self._heading = None
            return
        if tag in _BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._in_title:
            self.doc_title += data
            return
        self._buf.append(data)

    def _flush(self, heading: str | None = None) -> None:
        text = "".join(self._buf).replace("\u00a0", " ")
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        self._buf = []
        if heading:
            if text:
                self.blocks.append((heading, re.sub(r"\s+", " ", text).strip()))
            return
        if text:
            self.blocks.append(("p", text))


def _prepare_html(html: str) -> str:
    text = html.lstrip("\ufeff")
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text, count=1)
    return text


def _pick_title(toc_title: str, html_title: str, index: int) -> str:
    for candidate in (toc_title, html_title):
        text = re.sub(r"\s+", " ", candidate or "").strip()
        if text and not _SKIP_TITLE.fullmatch(text):
            return text
    fallback = (toc_title or html_title or "").strip()
    return fallback or f"第{index}章"


def _strip_leading_title(title: str, body: str) -> str:
    lines = body.split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and lines[0].strip() == (title or "").strip():
        lines.pop(0)
        while lines and not lines[0].strip():
            lines.pop(0)
    return "\n".join(lines).strip()


def _should_skip(title: str, body: str) -> bool:
    if _SKIP_TITLE.fullmatch((title or "").strip()) and count_chars(body) < 40:
        return True
    return count_chars(body) == 0 and count_chars(title) == 0


def _is_chapter_label(title: str) -> bool:
    return bool(_CHAPTER_LABEL.search((title or "").strip()))


def _is_chapter_heading_line(text: str) -> bool:
    line = (text or "").strip()
    if not line or "\n" in line or len(line) > 80:
        return False
    return any(pattern.fullmatch(line) for pattern in _HEADING_PATTERNS)


def _is_volume_heading_line(text: str) -> bool:
    line = (text or "").strip()
    if not line or "\n" in line or len(line) > 40 or _is_chapter_heading_line(line):
        return False
    return bool(VOLUME_PATTERN.fullmatch(line) or _VOLUME_LINE.fullmatch(line))


def _clip(text: str | None, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "")).strip()
    return cleaned[:limit]


def _decode(raw: bytes) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _opf_path(zf: zipfile.ZipFile, index: dict[str, str]) -> str:
    container = index.get("meta-inf/container.xml")
    if container is not None:
        try:
            root = _xml_root(zf.read(container))
        except (ET.ParseError, EpubImportError):
            root = None
        if root is not None:
            for el in root.iter():
                if _ln(el.tag) == "rootfile":
                    full = _attr(el, "full-path").replace("\\", "/").lstrip("/")
                    actual = index.get(full.lower())
                    if actual:
                        return actual.replace("\\", "/")
    for candidate in ("OEBPS/content.opf", "OPS/content.opf", "content.opf"):
        actual = index.get(candidate.lower())
        if actual:
            return actual.replace("\\", "/")
    opfs = [
        name
        for name in zf.namelist()
        if name.lower().endswith(".opf") and not name.lower().startswith("__macosx")
    ]
    if len(opfs) == 1:
        return opfs[0].replace("\\", "/")
    raise EpubImportError("EPUB 缺少目录")


def _xml_root(data: bytes) -> ET.Element:
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise EpubImportError("EPUB 的目录无法解析") from exc


def _metadata(root: ET.Element) -> tuple[str, str | None]:
    meta = next((el for el in root.iter() if _ln(el.tag) == "metadata"), None)
    if meta is None:
        return "", None
    title = ""
    authors: list[tuple[str, str]] = []
    for el in meta.iter():
        name = _ln(el.tag)
        if name == "title" and not title:
            title = re.sub(r"\s+", " ", "".join(el.itertext())).strip()
        elif name == "creator":
            text = re.sub(r"\s+", " ", "".join(el.itertext())).strip()
            if text:
                authors.append((text, _attr(el, "role")))
    author = next((text for text, role in authors if role == "aut"), "")
    if not author and authors:
        author = authors[0][0]
    return title, author or None


@dataclass
class _ManifestItem:
    id: str
    href: str
    media: str
    props: set[str]


def _manifest(root: ET.Element) -> dict[str, _ManifestItem]:
    found: dict[str, _ManifestItem] = {}
    for el in root.iter():
        if _ln(el.tag) != "item":
            continue
        iid = _attr(el, "id")
        href = _attr(el, "href")
        if not iid or not href:
            continue
        media = _attr(el, "media-type").split(";", 1)[0].strip().lower()
        props = {part for part in _attr(el, "properties").split() if part}
        found[iid] = _ManifestItem(iid, href, media, props)
    return found


def _spine(root: ET.Element, items: dict[str, _ManifestItem]) -> list[tuple[_ManifestItem, bool]]:
    spine_el = next((el for el in root.iter() if _ln(el.tag) == "spine"), None)
    if spine_el is None:
        raise EpubImportError("EPUB 缺少阅读顺序")
    ordered: list[tuple[_ManifestItem, bool]] = []
    for el in list(spine_el):
        if _ln(el.tag) != "itemref":
            continue
        item = items.get(_attr(el, "idref"))
        if item is None:
            continue
        ordered.append((item, _attr(el, "linear").lower() != "no"))
    return ordered


def _is_html(item: _ManifestItem, path: str) -> bool:
    if "ncx" in item.media or "dtbncx" in item.media:
        return False
    if item.media in _HTML_TYPES:
        return True
    return not item.media and path.lower().endswith((".xhtml", ".html", ".htm"))


def _resolve(base_dir: str, href: str) -> str:
    raw = unquote((href or "").split("#", 1)[0].split("?", 1)[0]).strip().replace("\\", "/")
    if not raw:
        return ""
    if raw.startswith("/"):
        path = posixpath.normpath(raw.lstrip("/"))
    else:
        path = posixpath.normpath(posixpath.join(base_dir, raw))
    if path == ".." or path.startswith("../"):
        return ""
    return path


def _read_zip(zf: zipfile.ZipFile, index: dict[str, str], path: str, budget: list[int]) -> bytes:
    actual = index.get(path.lower())
    if actual is None:
        raise EpubImportError("EPUB 缺少文件")
    info = zf.getinfo(actual)
    if info.file_size > _MAX_FILE:
        raise EpubImportError("EPUB 里有过大的文件")
    data = zf.read(actual)
    if len(data) > _MAX_FILE:
        raise EpubImportError("EPUB 里有过大的文件")
    budget[0] += len(data)
    if budget[0] > _MAX_READ:
        raise EpubImportError("EPUB 过大，无法导入")
    return data


def _ln(tag: str) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _tag(tag: str) -> str:
    return tag.lower().rsplit(":", 1)[-1]


def _attr(el: ET.Element | None, name: str) -> str:
    if el is None:
        return ""
    for key, value in el.attrib.items():
        if _ln(key) == name:
            return value or ""
    return ""


def _children(el: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in list(el) if isinstance(child.tag, str) and _ln(child.tag) == name]


def _child(el: ET.Element, name: str) -> ET.Element | None:
    kids = _children(el, name)
    return kids[0] if kids else None
