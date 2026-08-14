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
