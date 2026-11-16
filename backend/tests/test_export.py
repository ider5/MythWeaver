"""小说导出：多章顺序、txt/md 格式、空小说、不存在小说。"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.db import close_db, init_db
from app.llm.client import MockLLMClient, set_llm_client
from app.main import create_app
from app.models import Chapter, Novel
import app.db as db_mod


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    db_path = tmp_path / "export.db"
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


async def _seed_novel_with_chapters(session) -> int:
    novel = Novel(title="试写之书", genre="玄幻", status="ready", chapter_count=3, total_chars=30)
    session.add(novel)
    await session.flush()
    # 故意乱序插入，导出应按 index 排序
    session.add(
        Chapter(
            novel_id=novel.id,
            index=2,
            title="第二章 中段",
            content="中段正文。",
            char_count=5,
            status="raw",
        )
    )
    session.add(
        Chapter(
            novel_id=novel.id,
            index=1,
            title="第一章 开篇",
            content="开篇正文。",
            char_count=5,
            status="raw",
        )
    )
    session.add(
        Chapter(
            novel_id=novel.id,
            index=3,
            title="第三章 生成章",
            content="生成正文。",
            char_count=5,
            status="raw",
            is_generated=True,
        )
    )
    await session.commit()
    return novel.id


@pytest.mark.asyncio
async def test_export_txt_multi_chapter_order(client):
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel_id = await _seed_novel_with_chapters(session)

    r = await client.get(f"/api/novels/{novel_id}/export")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd
    assert "试写之书.txt" in cd or "filename*=UTF-8''" in cd

    text = r.content.decode("utf-8")
    pos1 = text.find("第一章 开篇")
    pos2 = text.find("第二章 中段")
    pos3 = text.find("第三章 生成章")
    assert 0 <= pos1 < pos2 < pos3
    assert "开篇正文。" in text
    assert "中段正文。" in text
    assert "生成正文。" in text
    # 章间应有空行分隔
    assert "开篇正文。\n\n第二章 中段" in text or "开篇正文。\r\n\r\n第二章 中段" in text


@pytest.mark.asyncio
async def test_export_md_format(client):
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel_id = await _seed_novel_with_chapters(session)

    r = await client.get(f"/api/novels/{novel_id}/export", params={"format": "md"})
    assert r.status_code == 200
    assert "markdown" in r.headers["content-type"] or "text/" in r.headers["content-type"]
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd
    assert ".md" in cd

    text = r.content.decode("utf-8")
    assert "# 第一章 开篇" in text
    assert "# 第二章 中段" in text
    assert text.index("# 第一章 开篇") < text.index("# 第二章 中段") < text.index("# 第三章 生成章")
    assert "开篇正文。" in text


@pytest.mark.asyncio
async def test_export_empty_novel(client):
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="空书", genre="都市", status="imported", chapter_count=0)
        session.add(novel)
        await session.commit()
        novel_id = novel.id

    r = await client.get(f"/api/novels/{novel_id}/export", params={"format": "txt"})
    assert r.status_code == 200
    assert r.content.decode("utf-8") == ""
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd


@pytest.mark.asyncio
async def test_export_novel_not_found(client):
    r = await client.get("/api/novels/99999/export")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_export_invalid_format(client):
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="格式校验", genre="言情", status="ready", chapter_count=0)
        session.add(novel)
        await session.commit()
        novel_id = novel.id

    r = await client.get(f"/api/novels/{novel_id}/export", params={"format": "pdf"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_export_epub_zip_structure(client):
    import io
    import zipfile

    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel_id = await _seed_novel_with_chapters(session)

    r = await client.get(f"/api/novels/{novel_id}/export", params={"format": "epub"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/epub+zip")
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = set(zf.namelist())
        assert "mimetype" in names
        assert "META-INF/container.xml" in names
        assert "OEBPS/content.opf" in names
        assert "OEBPS/toc.ncx" in names
        assert zf.read("mimetype") == b"application/epub+zip"
        assert any(n.startswith("OEBPS/chap_") for n in names)


async def _seed_volumes(session):
    novel = Novel(title="分卷之书", genre="玄幻", status="ready", chapter_count=3, author="叶凡")
    session.add(novel)
    await session.flush()
    rows = []
    for index, title, volume, content in (
        (1, "第一章 开篇", "第一卷", "卷一开篇。"),
        (2, "第二章 中段", "第一卷", "卷一中段。"),
        (3, "第三章 下卷", "第二卷", "卷二正文。"),
    ):
        row = Chapter(
            novel_id=novel.id,
            index=index,
            title=title,
            volume=volume,
            content=content,
            char_count=len(content),
            status="raw",
        )
        session.add(row)
        rows.append(row)
    await session.commit()
    for row in rows:
        await session.refresh(row)
    return novel.id, [row.id for row in rows]


@pytest.mark.asyncio
async def test_export_volume_keeps_order_and_drops_other_volumes(client):
    from urllib.parse import unquote

    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel_id, _ids = await _seed_volumes(session)

    r = await client.get(
        f"/api/novels/{novel_id}/export",
        params={"format": "txt", "volume": " 第一卷 "},
    )
    assert r.status_code == 200
    text = r.content.decode("utf-8")
    assert "卷一开篇。" in text
    assert "卷一中段。" in text
    assert "卷二正文。" not in text
    assert text.index("第一章 开篇") < text.index("第二章 中段")
    assert "第一卷" in unquote(r.headers["content-disposition"])

    md = await client.get(
        f"/api/novels/{novel_id}/export",
        params={"format": "md", "volume": "第一卷"},
    )
    body = md.content.decode("utf-8")
    assert "# 第一章 开篇" in body
    assert "# 第二章 中段" in body
    assert "第三章" not in body


@pytest.mark.asyncio
async def test_export_one_chapter_epub(client):
    import io
    import zipfile
    from urllib.parse import unquote

    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel_id, ids = await _seed_volumes(session)

    r = await client.get(
        f"/api/novels/{novel_id}/export",
        params={"format": "epub", "chapter_id": ids[2]},
    )
    assert r.status_code == 200
    assert "第三章" in unquote(r.headers["content-disposition"])
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        blob = "\n".join(
            zf.read(name).decode("utf-8")
            for name in zf.namelist()
            if name.endswith(".xhtml") or name.endswith(".opf")
        )
    assert "卷二正文。" in blob
    assert "卷一开篇。" not in blob
    assert "卷一中段。" not in blob
    assert "分卷之书 · 第三章 下卷" in blob


@pytest.mark.asyncio
async def test_export_scope_rejects_conflicts_and_misses(client):
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel_id, ids = await _seed_volumes(session)
        other = Novel(title="另一本", genre="都市", status="ready", chapter_count=1)
        session.add(other)
        await session.flush()
        foreign = Chapter(
            novel_id=other.id,
            index=1,
            title="外来章",
            content="不属于这本书。",
            char_count=8,
            status="raw",
        )
        session.add(foreign)
        await session.commit()
        await session.refresh(foreign)
        foreign_id = foreign.id

    both = await client.get(
        f"/api/novels/{novel_id}/export",
        params={"volume": "第一卷", "chapter_id": ids[0]},
    )
    assert both.status_code == 400

    empty = await client.get(f"/api/novels/{novel_id}/export", params={"volume": "  "})
    assert empty.status_code == 400

    missing = await client.get(f"/api/novels/{novel_id}/export", params={"volume": "第三卷"})
    assert missing.status_code == 404

    other_chapter = await client.get(
        f"/api/novels/{novel_id}/export",
        params={"chapter_id": foreign_id},
    )
    assert other_chapter.status_code == 404


@pytest.mark.asyncio
async def test_export_reference_stays_blocked_when_scoped(client):
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="参考样本", genre="言情", status="ready", role="reference", chapter_count=1)
        session.add(novel)
        await session.flush()
        chapter = Chapter(
            novel_id=novel.id,
            index=1,
            title="样本",
            volume="第一卷",
            content="只拆文风。",
            char_count=4,
            status="raw",
        )
        session.add(chapter)
        await session.commit()
        novel_id, chapter_id = novel.id, chapter.id

    by_chapter = await client.get(
        f"/api/novels/{novel_id}/export",
        params={"chapter_id": chapter_id},
    )
    by_volume = await client.get(f"/api/novels/{novel_id}/export", params={"volume": "第一卷"})
    assert by_chapter.status_code == 409
    assert by_volume.status_code == 409
