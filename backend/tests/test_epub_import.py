"""EPUB 导入：拆章、分卷，以及预览后确认为原稿。"""

from __future__ import annotations

import io
import zipfile

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from xml.sax.saxutils import escape

from app.config import get_settings
from app.db import close_db, init_db
from app.llm.client import MockLLMClient, set_llm_client
from app.main import create_app
from app.services.epub_export import build_epub
from app.services.epub_import import EpubImportError, parse_epub
import app.db as db_mod


def _xhtml(title: str, inner: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>{escape(title)}</title></head>
<body>{inner}</body>
</html>
"""


def pack_epub(
    *,
    title: str = "星海",
    author: str = "叶凡",
    documents: list[tuple[str, str, bool]],
    ncx: str | None = None,
    nav: str | None = None,
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
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
        manifest: list[str] = []
        spine: list[str] = []
        for i, (href, xhtml, linear) in enumerate(documents, start=1):
            zf.writestr(f"OEBPS/{href}", xhtml)
            manifest.append(
                f'<item id="id{i}" href="{href}" media-type="application/xhtml+xml"/>'
            )
            flag = "" if linear else ' linear="no"'
            spine.append(f'<itemref idref="id{i}"{flag}/>')
        if ncx:
            zf.writestr("OEBPS/toc.ncx", ncx)
            manifest.append(
                '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
            )
        if nav:
            zf.writestr("OEBPS/nav.xhtml", nav)
            manifest.append(
                '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
            )
        zf.writestr(
            "OEBPS/content.opf",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookId" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{escape(title)}</dc:title>
    <dc:creator>{escape(author)}</dc:creator>
    <dc:language>zh-CN</dc:language>
    <dc:identifier id="BookId">urn:test:book</dc:identifier>
  </metadata>
  <manifest>
{chr(10).join(manifest)}
  </manifest>
  <spine>
{chr(10).join(spine)}
  </spine>
</package>
""",
        )
    return buf.getvalue()


def test_parse_roundtrip_of_our_export():
    raw = build_epub(
        title="星海",
        author="叶凡",
        chapters=[
            ("第一章 晨光", "少年醒来。\n\n他说:甲\n乙,叶凡&苏婉。"),
            ("第二章 城门", "叶凡抵达青阳城。"),
        ],
    )
    book = parse_epub(raw)
    assert book.title == "星海"
    assert book.author == "叶凡"
    assert [c.title for c in book.chapters] == ["第一章 晨光", "第二章 城门"]
    assert book.chapters[0].content == "少年醒来。\n\n他说:甲\n乙,叶凡&苏婉。"
    assert book.chapters[1].content == "叶凡抵达青阳城。"
    assert book.chapters[0].volume is None


def test_parse_nested_ncx_volumes():
    ncx = """<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <navMap>
    <navPoint id="v1">
      <navLabel><text>第一卷 起</text></navLabel>
      <content src="v1.xhtml"/>
      <navPoint id="c1">
        <navLabel><text>第一章 晨光</text></navLabel>
        <content src="c1.xhtml"/>
      </navPoint>
      <navPoint id="c2">
        <navLabel><text>第二章 城门</text></navLabel>
        <content src="c2.xhtml"/>
      </navPoint>
    </navPoint>
    <navPoint id="v2">
      <navLabel><text>第二卷</text></navLabel>
      <content src="c3.xhtml"/>
      <navPoint id="c3">
        <navLabel><text>第三章 夜谈</text></navLabel>
        <content src="c3.xhtml"/>
      </navPoint>
    </navPoint>
  </navMap>
</ncx>
"""
    raw = pack_epub(
        documents=[
            (
                "v1.xhtml",
                _xhtml("第一卷 起", "<p>卷首语写在这里，说明这一卷从青阳城外的黎明写起，叶凡还不知道玉佩的来历。</p>"),
                True,
            ),
            ("c1.xhtml", _xhtml("第一章 晨光", "<p>少年醒来。</p>"), True),
            ("c2.xhtml", _xhtml("第二章 城门", "<p>叶凡抵达。</p>"), True),
            ("c3.xhtml", _xhtml("第三章 夜谈", "<p>苏婉低声说。</p>"), True),
        ],
        ncx=ncx,
    )
    book = parse_epub(raw)
    assert [(c.title, c.volume) for c in book.chapters] == [
        ("第一卷 起", "第一卷 起"),
        ("第一章 晨光", "第一卷 起"),
        ("第二章 城门", "第一卷 起"),
        ("第三章 夜谈", "第二卷"),
    ]
    assert "卷首语" in book.chapters[0].content
    assert "第一章" not in book.chapters[1].content


def test_parse_epub3_nav_volume_and_skips_cover():
    nav = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<body>
  <nav epub:type="toc">
    <ol>
      <li><a href="c1.xhtml">江湖篇</a>
        <ol>
          <li><a href="c1.xhtml">第一章 晨光</a></li>
          <li><a href="c2.xhtml">第二章 城门</a></li>
        </ol>
      </li>
    </ol>
  </nav>
</body>
</html>
"""
    raw = pack_epub(
        documents=[
            ("cover.xhtml", _xhtml("封面", "<p></p>"), False),
            ("c1.xhtml", _xhtml("第一章 晨光", "<p>叶凡&amp;苏婉</p>"), True),
            ("c2.xhtml", _xhtml("第二章 城门", "<p>甲<br/>乙</p>"), True),
        ],
        nav=nav,
    )
    book = parse_epub(raw)
    assert [c.title for c in book.chapters] == ["第一章 晨光", "第二章 城门"]
    assert {c.volume for c in book.chapters} == {"江湖篇"}
    assert book.chapters[0].content == "叶凡&苏婉"
    assert book.chapters[1].content == "甲\n乙"


def test_parse_single_file_headings_and_volume_line():
    html = _xhtml(
        "星海",
        "<p>第一卷 起</p><p>第一章 晨光</p><p>少年醒来。</p><h1>第二章 城门</h1><p>叶凡抵达。</p>",
    )
    book = parse_epub(pack_epub(documents=[("all.xhtml", html, True)]))
    assert [(c.title, c.volume, c.content) for c in book.chapters] == [
        ("第一章 晨光", "第一卷 起", "少年醒来。"),
        ("第二章 城门", "第一卷 起", "叶凡抵达。"),
    ]


def test_parse_rejects_garbage_and_empty_book():
    with pytest.raises(EpubImportError):
        parse_epub(b"not-an-epub")
    with pytest.raises(EpubImportError):
        parse_epub(build_epub(title="空", author=None, chapters=[]))


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    db_path = tmp_path / "epub.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("EMBEDDING_DIMS", "8")
    get_settings.cache_clear()

    import app.llm.client as llm_mod
    import app.services.tasks as tasks_mod

    db_mod.engine = None
    db_mod.SessionLocal = None
    llm_mod._client = None
    tasks_mod._queue = None

    set_llm_client(MockLLMClient(embed_dim=8, smart=True))
    await init_db()
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await close_db()
    get_settings.cache_clear()
    llm_mod._client = None
    db_mod.engine = None
    db_mod.SessionLocal = None
    tasks_mod._queue = None


@pytest.mark.asyncio
async def test_import_epub_preview_confirm_keeps_chapters(client):
    raw = build_epub(
        title="星海",
        author="叶凡",
        chapters=[("第一章 晨光", "少年醒来。"), ("第二章 城门", "叶凡抵达。")],
    )
    preview = await client.post(
        "/api/novels/import/preview",
        files={"file": ("随便.epub", raw, "application/epub+zip")},
        data={"title": "随便"},
    )
    assert preview.status_code == 200
    body = preview.json()
    assert body["title"] == "星海"
    assert body["author"] == "叶凡"
    assert body["chapter_count"] == 2
    assert body["chapters"][0]["title"] == "第一章 晨光"

    named = await client.post(
        "/api/novels/import/preview",
        files={"file": ("随便.epub", raw, "application/epub+zip")},
        data={"title": "我的书"},
    )
    assert named.json()["title"] == "我的书"

    saved = await client.post(
        "/api/novels/import/confirm",
        json={
            "import_token": body["import_token"],
            "title": body["title"],
            "author": body["author"],
            "genre": "玄幻",
            "role": "manuscript",
        },
    )
    assert saved.status_code == 200
    novel = saved.json()
    assert novel["author"] == "叶凡"
    assert novel["chapter_count"] == 2
    listed = await client.get(f"/api/novels/{novel['id']}/chapters")
    first = listed.json()[0]
    detail = await client.get(f"/api/novels/{novel['id']}/chapters/{first['id']}")
    assert detail.json()["content"] == "少年醒来。"
    assert detail.json()["title"] == "第一章 晨光"


@pytest.mark.asyncio
async def test_import_epub_errors_and_text_still_works(client):
    bad = await client.post(
        "/api/novels/import/preview",
        files={"file": ("坏.epub", b"hello", "application/epub+zip")},
        data={"title": "坏"},
    )
    assert bad.status_code == 400

    raw = build_epub(title="星海", author="叶凡", chapters=[("第一章", "正文。")])
    mixed = await client.post(
        "/api/novels/import/preview",
        files=[
            ("files", ("第一章.txt", "第一章\n\n正文".encode(), "text/plain")),
            ("files", ("书.epub", raw, "application/epub+zip")),
        ],
        data={"title": "混合"},
    )
    assert mixed.status_code == 400

    text = await client.post(
        "/api/novels/import/preview",
        files={"file": ("原稿.txt", "第一章 晨光\n\n少年醒来。\n\n第二章 城门\n\n叶凡抵达。".encode(), "text/plain")},
        data={"title": "原稿"},
    )
    assert text.status_code == 200
    assert text.json()["chapter_count"] == 2
    assert text.json().get("author") in (None, "")
