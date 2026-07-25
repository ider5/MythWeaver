"""章节删除：整章清理；按版本删除（中间/最新回退/删光清章）；版本报告按 version 返回。"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text

from app.config import get_settings
from app.db import close_db, init_db, is_vec_available
from app.llm.client import MockLLMClient, set_llm_client
from app.main import create_app
from app.models import Chapter, ChapterVersion, Novel, Outline, OutlineItem, Summary
import app.db as db_mod


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    db_path = tmp_path / "chapter_del.db"
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
async def test_versions_return_per_version_consistency_report(client):
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="版本报告", genre="玄幻", status="ready", chapter_count=1)
        session.add(novel)
        await session.flush()
        ch = Chapter(
            novel_id=novel.id,
            index=1,
            title="第一章",
            content="终稿正文",
            char_count=4,
            status="raw",
            is_generated=True,
        )
        session.add(ch)
        await session.flush()
        session.add(
            ChapterVersion(
                chapter_id=ch.id,
                version_type="generated",
                content="初稿正文",
                consistency_report=None,
            )
        )
        session.add(
            ChapterVersion(
                chapter_id=ch.id,
                version_type="critic_revised",
                content="终稿正文",
                consistency_report={"ok": False, "issues": [{"type": "x", "severity": "warn", "message": "m"}], "critic_rounds": 1},
            )
        )
        await session.commit()
        novel_id = novel.id
        chapter_id = ch.id

    r = await client.get(f"/api/novels/{novel_id}/chapters/{chapter_id}/versions")
    assert r.status_code == 200
    vers = r.json()
    assert len(vers) == 2
    assert vers[0]["consistency_report"] is None
    assert vers[1]["consistency_report"]["ok"] is False
    assert vers[1]["consistency_report"]["critic_rounds"] == 1


@pytest.mark.asyncio
async def test_delete_chapter_cleans_versions_summary_and_resets_outline(client):
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(
            title="删章",
            genre="玄幻",
            status="ready",
            chapter_count=5,
            total_chars=100,
        )
        session.add(novel)
        await session.flush()
        outline = Outline(
            novel_id=novel.id,
            title="大纲",
            status="confirmed",
            start_from_chapter=5,
        )
        session.add(outline)
        await session.flush()
        item = OutlineItem(
            outline_id=outline.id,
            order=1,
            title="第五章",
            summary="s",
            key_points=[],
            status="done",
        )
        session.add(item)
        await session.flush()
        # 保留一章更早的，用于校验 chapter_count 回退
        keep = Chapter(
            novel_id=novel.id,
            index=3,
            title="第三章",
            content="保留",
            char_count=2,
            status="embedded",
            is_generated=False,
        )
        session.add(keep)
        ch = Chapter(
            novel_id=novel.id,
            index=5,
            title="第五章",
            content="待删正文" * 10,
            char_count=40,
            status="embedded",
            is_generated=True,
            outline_item_id=item.id,
            embedding_json=[0.1] * 8,
        )
        session.add(ch)
        await session.flush()
        session.add(
            ChapterVersion(
                chapter_id=ch.id,
                version_type="generated",
                content=ch.content,
                consistency_report={"ok": True, "issues": [], "critic_rounds": 0},
            )
        )
        session.add(
            Summary(
                novel_id=novel.id,
                chapter_id=ch.id,
                level="chapter",
                content="章摘要",
            )
        )
        if is_vec_available():
            await session.execute(
                text(
                    "INSERT INTO chapter_embeddings(chapter_id, embedding) "
                    "VALUES (:cid, :emb)"
                ),
                {
                    "cid": ch.id,
                    "emb": __import__("struct").pack("8f", *([0.1] * 8)),
                },
            )
        await session.commit()
        novel_id = novel.id
        chapter_id = ch.id
        item_id = item.id
        keep_id = keep.id

    r = await client.delete(f"/api/novels/{novel_id}/chapters/{chapter_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["chapter_id"] == chapter_id
    assert body["outline_item_id"] == item_id
    assert body["outline_item_reset"] is True

    async with db_mod.SessionLocal() as session:
        assert await session.get(Chapter, chapter_id) is None
        assert await session.get(Chapter, keep_id) is not None
        ver_count = await session.scalar(
            select(func.count())
            .select_from(ChapterVersion)
            .where(ChapterVersion.chapter_id == chapter_id)
        )
        assert ver_count == 0
        sum_count = await session.scalar(
            select(func.count()).select_from(Summary).where(Summary.chapter_id == chapter_id)
        )
        assert sum_count == 0
        item = await session.get(OutlineItem, item_id)
        assert item is not None
        assert item.status == "pending"
        novel = await session.get(Novel, novel_id)
        assert novel is not None
        assert novel.chapter_count == 3
        assert novel.total_chars == 60
        if is_vec_available():
            row = (
                await session.execute(
                    text("SELECT chapter_id FROM chapter_embeddings WHERE chapter_id = :cid"),
                    {"cid": chapter_id},
                )
            ).fetchone()
            assert row is None

    r = await client.get(f"/api/novels/{novel_id}/chapters/by-outline-item/{item_id}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_chapter_not_found(client):
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="空", genre="玄幻", status="ready")
        session.add(novel)
        await session.commit()
        novel_id = novel.id

    r = await client.delete(f"/api/novels/{novel_id}/chapters/99999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_middle_version_keeps_chapter_and_outline(client):
    """删中间版本：正文与大纲不动。"""
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="删中间版", genre="玄幻", status="ready", chapter_count=1, total_chars=12)
        session.add(novel)
        await session.flush()
        outline = Outline(novel_id=novel.id, title="大纲", status="confirmed", start_from_chapter=1)
        session.add(outline)
        await session.flush()
        item = OutlineItem(
            outline_id=outline.id,
            order=1,
            title="第一章",
            summary="s",
            key_points=[],
            status="done",
        )
        session.add(item)
        await session.flush()
        ch = Chapter(
            novel_id=novel.id,
            index=1,
            title="第一章",
            content="终稿正文XX",
            char_count=6,
            status="raw",
            is_generated=True,
            outline_item_id=item.id,
        )
        session.add(ch)
        await session.flush()
        v1 = ChapterVersion(
            chapter_id=ch.id,
            version_type="generated",
            content="初稿正文AA",
            consistency_report=None,
        )
        session.add(v1)
        await session.flush()
        v2 = ChapterVersion(
            chapter_id=ch.id,
            version_type="critic_revised",
            content="中稿正文BB",
            consistency_report={"ok": False, "issues": [], "critic_rounds": 1},
            parent_version_id=v1.id,
        )
        session.add(v2)
        await session.flush()
        v3 = ChapterVersion(
            chapter_id=ch.id,
            version_type="user_edited",
            content="终稿正文XX",
            consistency_report={"ok": True, "issues": [], "critic_rounds": 0},
            parent_version_id=v2.id,
        )
        session.add(v3)
        await session.commit()
        novel_id, chapter_id, item_id = novel.id, ch.id, item.id
        mid_id, latest_id = v2.id, v3.id

    r = await client.delete(f"/api/novels/{novel_id}/chapters/{chapter_id}/versions/{mid_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["chapter_deleted"] is False
    assert body["content_rolled_back"] is False
    assert body["remaining_versions"] == 2
    assert body["outline_item_reset"] is False

    async with db_mod.SessionLocal() as session:
        ch = await session.get(Chapter, chapter_id)
        assert ch is not None
        assert ch.content == "终稿正文XX"
        assert ch.char_count == 6
        assert await session.get(ChapterVersion, mid_id) is None
        assert await session.get(ChapterVersion, latest_id) is not None
        item = await session.get(OutlineItem, item_id)
        assert item is not None
        assert item.status == "done"
        # 子版本的 parent 因 SET NULL 被清空
        latest = await session.get(ChapterVersion, latest_id)
        assert latest is not None
        assert latest.parent_version_id is None


@pytest.mark.asyncio
async def test_delete_latest_version_rolls_back_content(client):
    """删最新（当前正文）版本：content 回退到剩余最新一版，大纲仍 done。"""
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="删最新版", genre="玄幻", status="ready", chapter_count=1, total_chars=4)
        session.add(novel)
        await session.flush()
        outline = Outline(novel_id=novel.id, title="大纲", status="confirmed", start_from_chapter=1)
        session.add(outline)
        await session.flush()
        item = OutlineItem(
            outline_id=outline.id,
            order=1,
            title="第一章",
            summary="s",
            key_points=[],
            status="done",
        )
        session.add(item)
        await session.flush()
        ch = Chapter(
            novel_id=novel.id,
            index=1,
            title="第一章",
            content="终稿正文",
            char_count=4,
            status="raw",
            is_generated=True,
            outline_item_id=item.id,
        )
        session.add(ch)
        await session.flush()
        v1 = ChapterVersion(
            chapter_id=ch.id,
            version_type="generated",
            content="初稿正文",
            consistency_report={"ok": True, "issues": [], "critic_rounds": 0},
        )
        session.add(v1)
        await session.flush()
        v2 = ChapterVersion(
            chapter_id=ch.id,
            version_type="critic_revised",
            content="终稿正文",
            consistency_report={"ok": False, "issues": [{"type": "x", "severity": "warn", "message": "m"}], "critic_rounds": 1},
            parent_version_id=v1.id,
        )
        session.add(v2)
        await session.commit()
        novel_id, chapter_id, item_id = novel.id, ch.id, item.id
        keep_id, del_id = v1.id, v2.id

    r = await client.delete(f"/api/novels/{novel_id}/chapters/{chapter_id}/versions/{del_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["chapter_deleted"] is False
    assert body["content_rolled_back"] is True
    assert body["remaining_versions"] == 1
    assert body["outline_item_reset"] is False
    assert body["active_content"] == "初稿正文"

    async with db_mod.SessionLocal() as session:
        ch = await session.get(Chapter, chapter_id)
        assert ch is not None
        assert ch.content == "初稿正文"
        assert ch.char_count == 4
        assert await session.get(ChapterVersion, del_id) is None
        keep = await session.get(ChapterVersion, keep_id)
        assert keep is not None
        assert keep.consistency_report is not None
        assert keep.consistency_report["ok"] is True
        item = await session.get(OutlineItem, item_id)
        assert item is not None
        assert item.status == "done"
        novel = await session.get(Novel, novel_id)
        assert novel is not None
        assert novel.total_chars == 4
        assert novel.chapter_count == 1


@pytest.mark.asyncio
async def test_delete_last_version_removes_chapter_and_resets_outline(client):
    """删光最后一版：整章清除，大纲回 pending。"""
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="删末版", genre="玄幻", status="ready", chapter_count=2, total_chars=10)
        session.add(novel)
        await session.flush()
        outline = Outline(novel_id=novel.id, title="大纲", status="confirmed", start_from_chapter=2)
        session.add(outline)
        await session.flush()
        item = OutlineItem(
            outline_id=outline.id,
            order=1,
            title="第二章",
            summary="s",
            key_points=[],
            status="done",
        )
        session.add(item)
        await session.flush()
        keep = Chapter(
            novel_id=novel.id,
            index=1,
            title="第一章",
            content="保留",
            char_count=2,
            status="raw",
            is_generated=False,
        )
        session.add(keep)
        ch = Chapter(
            novel_id=novel.id,
            index=2,
            title="第二章",
            content="仅此一版",
            char_count=4,
            status="embedded",
            is_generated=True,
            outline_item_id=item.id,
            embedding_json=[0.2] * 8,
        )
        session.add(ch)
        await session.flush()
        v = ChapterVersion(
            chapter_id=ch.id,
            version_type="generated",
            content="仅此一版",
            consistency_report={"ok": True, "issues": [], "critic_rounds": 0},
        )
        session.add(v)
        session.add(
            Summary(novel_id=novel.id, chapter_id=ch.id, level="chapter", content="章摘要")
        )
        if is_vec_available():
            await session.execute(
                text(
                    "INSERT INTO chapter_embeddings(chapter_id, embedding) "
                    "VALUES (:cid, :emb)"
                ),
                {
                    "cid": ch.id,
                    "emb": __import__("struct").pack("8f", *([0.2] * 8)),
                },
            )
        await session.commit()
        novel_id, chapter_id, item_id, ver_id, keep_id = novel.id, ch.id, item.id, v.id, keep.id

    r = await client.delete(f"/api/novels/{novel_id}/chapters/{chapter_id}/versions/{ver_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["chapter_deleted"] is True
    assert body["remaining_versions"] == 0
    assert body["outline_item_reset"] is True
    assert body["outline_item_id"] == item_id

    async with db_mod.SessionLocal() as session:
        assert await session.get(Chapter, chapter_id) is None
        assert await session.get(Chapter, keep_id) is not None
        assert await session.get(ChapterVersion, ver_id) is None
        sum_count = await session.scalar(
            select(func.count()).select_from(Summary).where(Summary.chapter_id == chapter_id)
        )
        assert sum_count == 0
        item = await session.get(OutlineItem, item_id)
        assert item is not None
        assert item.status == "pending"
        novel = await session.get(Novel, novel_id)
        assert novel is not None
        assert novel.chapter_count == 1
        assert novel.total_chars == 6
        if is_vec_available():
            row = (
                await session.execute(
                    text("SELECT chapter_id FROM chapter_embeddings WHERE chapter_id = :cid"),
                    {"cid": chapter_id},
                )
            ).fetchone()
            assert row is None


@pytest.mark.asyncio
async def test_delete_version_not_found(client):
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="无版本", genre="玄幻", status="ready")
        session.add(novel)
        await session.flush()
        ch = Chapter(
            novel_id=novel.id,
            index=1,
            title="第一章",
            content="x",
            char_count=1,
            status="raw",
            is_generated=True,
        )
        session.add(ch)
        await session.commit()
        novel_id, chapter_id = novel.id, ch.id

    r = await client.delete(f"/api/novels/{novel_id}/chapters/{chapter_id}/versions/99999")
    assert r.status_code == 404
