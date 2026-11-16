"""Minimal EPUB 2 builder (zip + xhtml) with no third-party deps."""

from __future__ import annotations

import html
import io
import re
import zipfile
from typing import Iterable


def _slug(text: str, fallback: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff\-]+", "-", (text or "").strip(), flags=re.UNICODE)
    cleaned = cleaned.strip("-") or fallback
    return cleaned[:80]


def _para_blocks(body: str) -> str:
    chunks = [p.strip() for p in re.split(r"\n\s*\n", body or "") if p.strip()]
    if not chunks:
        return "<p></p>"
    return "\n".join(f"<p>{html.escape(p).replace(chr(10), '<br/>')}</p>" for p in chunks)


def build_epub(
    *,
    title: str,
    author: str | None,
    chapters: Iterable[tuple[str, str]],
) -> bytes:
    """Return EPUB bytes. chapters: (chapter_title, body_text)."""
    items = list(chapters)
    book_title = (title or "未命名").strip() or "未命名"
    book_author = (author or "匿名").strip() or "匿名"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        manifest = []
        spine = []
        nav_points = []
        for i, (ch_title, body) in enumerate(items, start=1):
            fname = f"chap_{i:04d}.xhtml"
            safe_title = html.escape((ch_title or f"第{i}章").strip() or f"第{i}章")
            zf.writestr(
                f"OEBPS/{fname}",
                f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN">
<head>
  <title>{safe_title}</title>
  <link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
  <h1>{safe_title}</h1>
  {_para_blocks(body)}
</body>
</html>
""",
            )
            mid = f"chap{i}"
            manifest.append(
                f'    <item id="{mid}" href="{fname}" media-type="application/xhtml+xml"/>'
            )
            spine.append(f'    <itemref idref="{mid}"/>')
            nav_points.append(
                f"""    <navPoint id="nav{i}" playOrder="{i}">
      <navLabel><text>{safe_title}</text></navLabel>
      <content src="{fname}"/>
    </navPoint>"""
            )

        zf.writestr(
            "OEBPS/style.css",
            """body{font-family:serif;line-height:1.7;margin:1.2em;}
h1{font-size:1.4em;margin:0 0 1em;font-weight:600;}
p{margin:0 0 0.9em;text-indent:2em;}
""",
        )
        manifest.append('    <item id="css" href="style.css" media-type="text/css"/>')
        manifest.append('    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>')

        uid = _slug(book_title, "mythweaver")
        zf.writestr(
            "OEBPS/content.opf",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookId" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>{html.escape(book_title)}</dc:title>
    <dc:creator opf:role="aut">{html.escape(book_author)}</dc:creator>
    <dc:language>zh-CN</dc:language>
    <dc:identifier id="BookId">urn:mythweaver:{html.escape(uid)}</dc:identifier>
  </metadata>
  <manifest>
{chr(10).join(manifest)}
  </manifest>
  <spine toc="ncx">
{chr(10).join(spine)}
  </spine>
</package>
""",
        )
        zf.writestr(
            "OEBPS/toc.ncx",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN" "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="urn:mythweaver:{html.escape(uid)}"/>
  </head>
  <docTitle><text>{html.escape(book_title)}</text></docTitle>
  <navMap>
{chr(10).join(nav_points)}
  </navMap>
</ncx>
""",
        )
    return buf.getvalue()
