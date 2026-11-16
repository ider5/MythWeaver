"""单本 ZIP 备份：导出行，恢复为一本新小说。"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime
from urllib.parse import quote

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text

from app.config import get_settings
from app.db import close_db, init_db, is_vec_available
from app.llm.client import MockLLMClient, set_llm_client
from app.main import create_app
from app.models import (
    AsyncTask,
    BibleProposal,
    Chapter,
    ChapterVersion,
    Character,
    CostLog,
    Novel,
    Outline,
    OutlineItem,
    PlotThread,
    RecurrentMemory,
    StyleSample,
    Summary,
    WorldSetting,
)
import app.db as db_mod

CREATED = datetime(2024, 5, 6, 7, 8, 9)


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    db_path = tmp_path / "backup.db"
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


def _zip(tables: dict, *, version: int = 1, extra: dict | None = None, counts: dict | None = None) -> bytes:
    manifest: dict = {"format": "mythweaver-novel-backup", "version": version}
    if counts is not None:
        manifest["tables"] = counts
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest).encode())
        for key, rows in tables.items():
            zf.writestr(f"rows/{key}.json", json.dumps(rows, ensure_ascii=False).encode())
        for name, blob in (extra or {}).items():
            zf.writestr(name, blob)
    return buffer.getvalue()


def _unzip(payload: bytes) -> tuple[dict, dict]:
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        tables = {
            name: json.loads(zf.read(name))
            for name in zf.namelist()
            if name.startswith("rows/") and name.endswith(".json")
        }
    return manifest, tables


async def _restore(client: AsyncClient, payload: bytes, title: str | None = None):
    kwargs: dict = {"files": {"file": ("book.mythweaver.zip", payload, "application/zip")}}
    if title is not None:
        kwargs["data"] = {"title": title}
    return await client.post("/api/novels/backup/restore", **kwargs)


def _ts(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(microsecond=0).isoformat()


async def _snapshot(session, novel_id: int) -> dict:
    novel = await session.get(Novel, novel_id)
    assert novel is not None
    chapters = (
        await session.execute(
            select(Chapter).where(Chapter.novel_id == novel_id).order_by(Chapter.index, Chapter.id)
        )
    ).scalars().all()
    chapter_index = {chapter.id: chapter.index for chapter in chapters}
    versions = (
        await session.execute(
            select(ChapterVersion)
            .join(Chapter, ChapterVersion.chapter_id == Chapter.id)
            .where(Chapter.novel_id == novel_id)
            .order_by(Chapter.index, ChapterVersion.id)
        )
    ).scalars().all()
    version_content = {version.id: version.content for version in versions}
    items = (
        await session.execute(
            select(OutlineItem)
            .join(Outline, OutlineItem.outline_id == Outline.id)
            .where(Outline.novel_id == novel_id)
            .order_by(OutlineItem.order, OutlineItem.id)
        )
    ).scalars().all()
    item_order = {item.id: item.order for item in items}
    outlines = (
        await session.execute(select(Outline).where(Outline.novel_id == novel_id).order_by(Outline.id))
    ).scalars().all()
    summaries = (
        await session.execute(select(Summary).where(Summary.novel_id == novel_id).order_by(Summary.id))
    ).scalars().all()
    characters = (
        await session.execute(select(Character).where(Character.novel_id == novel_id).order_by(Character.id))
    ).scalars().all()
    worlds = (
        await session.execute(
            select(WorldSetting).where(WorldSetting.novel_id == novel_id).order_by(WorldSetting.id)
        )
    ).scalars().all()
    threads = (
        await session.execute(select(PlotThread).where(PlotThread.novel_id == novel_id).order_by(PlotThread.id))
    ).scalars().all()
    proposals = (
        await session.execute(
            select(BibleProposal).where(BibleProposal.novel_id == novel_id).order_by(BibleProposal.id)
        )
    ).scalars().all()
    samples = (
        await session.execute(
            select(StyleSample).where(StyleSample.novel_id == novel_id).order_by(StyleSample.id)
        )
    ).scalars().all()
    memory = (
        await session.execute(select(RecurrentMemory).where(RecurrentMemory.novel_id == novel_id))
    ).scalar_one_or_none()
    versions_by_chapter: dict[int, list] = {}
    for version in versions:
        versions_by_chapter.setdefault(chapter_index[version.chapter_id], []).append(
            {
                "version_type": version.version_type,
                "content": version.content,
                "consistency_report": version.consistency_report,
                "parent_content": version_content.get(version.parent_version_id),
                "created_at": _ts(version.created_at),
            }
        )
    return {
        "novel": {
            "title": novel.title,
            "author": novel.author,
            "genre": novel.genre,
            "role": novel.role,
            "origin": novel.origin,
            "description": novel.description,
            "premise": novel.premise,
            "writing_style": novel.writing_style,
            "source_path": novel.source_path,
            "status": novel.status,
            "total_chars": novel.total_chars,
            "chapter_count": novel.chapter_count,
            "avg_chapter_chars": novel.avg_chapter_chars,
            "median_chapter_chars": novel.median_chapter_chars,
            "created_at": _ts(novel.created_at),
            "updated_at": _ts(novel.updated_at),
        },
        "chapters": [
            {
                "index": chapter.index,
                "title": chapter.title,
                "volume": chapter.volume,
                "content": chapter.content,
                "char_count": chapter.char_count,
                "status": chapter.status,
                "is_generated": chapter.is_generated,
                "embedding": chapter.embedding_json,
                "item_order": item_order.get(chapter.outline_item_id),
                "created_at": _ts(chapter.created_at),
                "versions": versions_by_chapter.get(chapter.index, []),
            }
            for chapter in chapters
        ],
        "outlines": [
            {
                "title": outline.title,
                "status": outline.status,
                "start_from_chapter": outline.start_from_chapter,
                "created_at": _ts(outline.created_at),
            }
            for outline in outlines
        ],
        "items": [
            {
                "order": item.order,
                "title": item.title,
                "summary": item.summary,
                "key_points": item.key_points,
                "purpose": item.purpose,
                "conflict": item.conflict,
                "suspense_hook": item.suspense_hook,
                "characters": item.characters,
                "status": item.status,
            }
            for item in items
        ],
        "summaries": [
            {
                "level": row.level,
                "volume_key": row.volume_key,
                "content": row.content,
                "chapter_index": chapter_index.get(row.chapter_id),
            }
            for row in summaries
        ],
        "characters": [
            {
                "name": row.name,
                "aliases": row.aliases,
                "role": row.role,
                "personality": row.personality,
                "relationships": row.relationships,
                "last_appear_chapter": row.last_appear_chapter,
            }
            for row in characters
        ],
        "worlds": [
            {
                "category": row.category,
                "title": row.title,
                "content": row.content,
                "do_not_violate": row.do_not_violate,
            }
            for row in worlds
        ],
        "threads": [
            {
                "title": row.title,
                "description": row.description,
                "thread_type": row.thread_type,
                "status": row.status,
                "introduced_chapter": row.introduced_chapter,
                "resolved_chapter": row.resolved_chapter,
                "planned_resolve_chapter": row.planned_resolve_chapter,
            }
            for row in threads
        ],
        "proposals": [
            {
                "chapter_index": chapter_index.get(row.chapter_id),
                "status": row.status,
                "content_hash": row.content_hash,
                "changes": row.changes,
                "applied_ids": row.applied_ids,
            }
            for row in proposals
        ],
        "samples": [
            {
                "content": row.content,
                "reason": row.reason,
                "chapter_index": chapter_index.get(row.chapter_id),
            }
            for row in samples
        ],
        "memory": None
        if memory is None
        else {
            "last_chapter_index": memory.last_chapter_index,
            "ending_state": memory.ending_state,
            "character_positions": memory.character_positions,
            "timeline_cursor": memory.timeline_cursor,
            "open_threads": memory.open_threads,
        },
    }


async def _seed_full(session) -> dict:
    novel = Novel(
        title="备份之书",
        author="甲",
        genre="仙侠",
        role="manuscript",
        origin="scratch",
        description="简介",
        premise="一个足够具体的前提",
        writing_style="冷",
        source_path="/tmp/should-not-restore.txt",
        status="generating",
        total_chars=12,
        chapter_count=2,
        avg_chapter_chars=6,
        median_chapter_chars=6,
        created_at=CREATED,
        updated_at=CREATED,
    )
    session.add(novel)
    await session.flush()
    outline = Outline(
        novel_id=novel.id,
        title="续写大纲",
        status="confirmed",
        start_from_chapter=3,
        created_at=CREATED,
        updated_at=CREATED,
    )
    session.add(outline)
    await session.flush()
    item = OutlineItem(
        outline_id=outline.id,
        order=1,
        title="目标章",
        summary="概要",
        key_points=["甲", "乙"],
        purpose="小目标",
        conflict="冲突",
        suspense_hook="钩子",
        characters=["甲"],
        status="done",
    )
    session.add(item)
    await session.flush()
    chapter1 = Chapter(
        novel_id=novel.id,
        index=1,
        title="第一章",
        volume="卷一",
        content="他说「走」。\n雨还在下。",
        char_count=4,
        status="embedded",
        is_generated=False,
        embedding_json=[0.25] * 8,
        created_at=CREATED,
        updated_at=CREATED,
    )
    chapter2 = Chapter(
        novel_id=novel.id,
        index=2,
        title="第二章",
        content="生成正文。",
        char_count=5,
        status="extracted",
        is_generated=True,
        outline_item_id=item.id,
        created_at=CREATED,
        updated_at=CREATED,
    )
    session.add_all([chapter1, chapter2])
    await session.flush()
    version1 = ChapterVersion(
        chapter_id=chapter2.id,
        version_type="generated",
        content="初稿",
        created_at=CREATED,
    )
    session.add(version1)
    await session.flush()
    version2 = ChapterVersion(
        chapter_id=chapter2.id,
        version_type="critic_revised",
        content="修订稿",
        parent_version_id=version1.id,
        consistency_report={
            "ok": False,
            "issues": [{"type": "alias", "severity": "warning", "message": "别称"}],
            "critic_rounds": 1,
        },
        created_at=CREATED,
    )
    session.add(version2)
    session.add(
        Summary(
            novel_id=novel.id,
            chapter_id=chapter1.id,
            level="chapter",
            content="章摘要",
            created_at=CREATED,
        )
    )
    session.add(
        Summary(
            novel_id=novel.id,
            chapter_id=None,
            level="volume",
            volume_key="卷一",
            content="卷摘要",
            created_at=CREATED,
        )
    )
    session.add(
        Character(
            novel_id=novel.id,
            name="甲",
            aliases=["阿甲"],
            role="主角",
            personality="寡言",
            relationships={"师徒": {"target": "乙", "note": "记仇"}},
            last_appear_chapter=2,
            created_at=CREATED,
            updated_at=CREATED,
        )
    )
    session.add(
        WorldSetting(
            novel_id=novel.id,
            category="规则",
            title="禁飞",
            content="城内不能飞。",
            do_not_violate="不得飞过城墙",
            created_at=CREATED,
            updated_at=CREATED,
        )
    )
    session.add(
        PlotThread(
            novel_id=novel.id,
            title="玉佩",
            description="丢在雨里",
            thread_type="伏笔",
            status="未回收",
            introduced_chapter=1,
            planned_resolve_chapter=6,
            created_at=CREATED,
            updated_at=CREATED,
        )
    )
    session.add(
        BibleProposal(
            novel_id=novel.id,
            chapter_id=chapter2.id,
            chapter_index=2,
            status="pending",
            content_hash="abc",
            changes=[{"id": "c1", "kind": "character", "op": "add", "label": "丙"}],
            applied_ids=[],
            created_at=CREATED,
            updated_at=CREATED,
        )
    )
    session.add(
        StyleSample(
            novel_id=novel.id,
            chapter_id=chapter1.id,
            content="短句。冷。",
            reason="开篇",
            created_at=CREATED,
        )
    )
    session.add(
        RecurrentMemory(
            novel_id=novel.id,
            last_chapter_index=2,
            ending_state="雨夜",
            character_positions={"甲": "城门"},
            timeline_cursor="第三日",
            open_threads=["玉佩"],
            updated_at=CREATED,
        )
    )
    session.add(CostLog(novel_id=novel.id, purpose="generation", cost_usd=0.2))
    session.add(AsyncTask(novel_id=novel.id, task_type="ingest", status="failed", message="旧任务"))
    other = Novel(title="旁观之书", genre="都市", status="ready", role="manuscript")
    session.add(other)
    await session.flush()
    session.add(Character(novel_id=other.id, name="旁观者", aliases=[], relationships={}))
    await session.commit()
    return {"novel_id": novel.id, "other_id": other.id, "chapter2_id": chapter2.id}


@pytest.mark.asyncio
async def test_backup_roundtrip_creates_new_novel(client):
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        seeded = await _seed_full(session)
        before = await _snapshot(session, seeded["novel_id"])

    downloaded = await client.get(f"/api/novels/{seeded['novel_id']}/backup")
    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"PK")
    assert "application/zip" in downloaded.headers["content-type"]
    disposition = downloaded.headers["content-disposition"]
    assert "filename*=UTF-8''" in disposition
    assert quote("备份之书.mythweaver.zip") in disposition

    manifest, tables = _unzip(downloaded.content)
    assert manifest["format"] == "mythweaver-novel-backup"
    assert manifest["version"] == 1
    assert manifest["source_novel_id"] == seeded["novel_id"]
    assert manifest["omitted"] == ["async_tasks", "cost_logs", "chapter_embeddings"]
    assert "rows/async_tasks.json" not in zipfile.ZipFile(io.BytesIO(downloaded.content)).namelist()
    dumped = json.dumps(tables, ensure_ascii=False)
    assert "旁观者" not in dumped
    assert tables["rows/novels.json"][0]["status"] == "generating"
    assert tables["rows/novels.json"][0]["source_path"] == "/tmp/should-not-restore.txt"
    assert "旧任务" not in dumped

    first = await _restore(client, downloaded.content)
    assert first.status_code == 200
    copy_id = first.json()["id"]
    assert copy_id != seeded["novel_id"]
    assert first.json()["title"] == "备份之书"
    assert first.json()["status"] == "ready"
    assert first.json()["origin"] == "scratch"
    assert first.json()["premise"] == "一个足够具体的前提"

    second = await _restore(client, downloaded.content)
    assert second.status_code == 200
    assert second.json()["id"] not in {seeded["novel_id"], copy_id}

    async with db_mod.SessionLocal() as session:
        original = await session.get(Novel, seeded["novel_id"])
        assert original is not None
        assert original.status == "generating"
        assert original.source_path == "/tmp/should-not-restore.txt"
        restored = await _snapshot(session, copy_id)
        expected = json.loads(json.dumps(before))
        expected["novel"]["status"] = "ready"
        expected["novel"]["source_path"] = None
        assert restored == expected

        original_chapter = await session.get(Chapter, seeded["chapter2_id"])
        assert original_chapter is not None
        original_chapter.content = "只改原书"
        await session.commit()
        copied_chapters = (
            await session.execute(select(Chapter).where(Chapter.novel_id == copy_id, Chapter.index == 2))
        ).scalars().all()
        assert copied_chapters[0].content == "生成正文。"
        assert copied_chapters[0].id != original_chapter.id

        if is_vec_available():
            rows = (
                await session.execute(
                    text(
                        "SELECT chapter_id FROM chapter_embeddings "
                        "WHERE chapter_id = ("
                        "SELECT id FROM chapters WHERE novel_id = :nid AND \"index\" = 1"
                        ")"
                    ),
                    {"nid": copy_id},
                )
            ).fetchall()
            assert len(rows) == 1

        assert await session.scalar(select(func.count()).select_from(CostLog)) == 1
        assert await session.scalar(select(func.count()).select_from(AsyncTask)) == 1
        other_names = (
            await session.execute(select(Character.name).where(Character.novel_id == seeded["other_id"]))
        ).scalars().all()
        assert other_names == ["旁观者"]


@pytest.mark.asyncio
async def test_reference_backup_while_book_export_is_blocked(client):
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="参考拆解", genre="言情", role="reference", status="ready", chapter_count=1)
        session.add(novel)
        await session.flush()
        session.add(
            Chapter(
                novel_id=novel.id,
                index=1,
                title="样本",
                content="只拆文风。",
                char_count=5,
                status="raw",
            )
        )
        await session.commit()
        novel_id = novel.id

    exported = await client.get(f"/api/novels/{novel_id}/export")
    assert exported.status_code == 409
    backed_up = await client.get(f"/api/novels/{novel_id}/backup")
    assert backed_up.status_code == 200

    restored = await _restore(client, backed_up.content)
    assert restored.status_code == 200
    body = restored.json()
    assert body["id"] != novel_id
    assert body["role"] == "reference"
    assert body["title"] == "参考拆解"
    again = await client.get(f"/api/novels/{body['id']}/export")
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_restore_blank_scratch_and_title_override(client):
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(
            title="空开书",
            genre="玄幻",
            origin="scratch",
            status="blank",
            premise="从一句前提写起",
            writing_style="白描",
            created_at=CREATED,
            updated_at=CREATED,
        )
        session.add(novel)
        await session.commit()
        novel_id = novel.id

    payload = (await client.get(f"/api/novels/{novel_id}/backup")).content
    restored = await _restore(client, payload, title="新开的书")
    assert restored.status_code == 200
    body = restored.json()
    assert body["id"] != novel_id
    assert body["title"] == "新开的书"
    assert body["origin"] == "scratch"
    assert body["status"] == "blank"
    assert body["premise"] == "从一句前提写起"
    assert body["writing_style"] == "白描"
    original = await client.get(f"/api/novels/{novel_id}")
    assert original.json()["title"] == "空开书"
    assert original.json()["status"] == "blank"


@pytest.mark.asyncio
async def test_restore_clears_generating_outline_item(client):
    """备份可以发生在生成中途。新书的大纲条目不能继续卡在 generating。"""
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="写到一半", genre="玄幻", status="generating", chapter_count=1)
        session.add(novel)
        await session.flush()
        outline = Outline(
            novel_id=novel.id, title="大纲", status="confirmed", start_from_chapter=1
        )
        session.add(outline)
        await session.flush()
        item = OutlineItem(
            outline_id=outline.id,
            order=1,
            title="第一章",
            summary="s",
            key_points=[],
            status="generating",
        )
        session.add(item)
        await session.flush()
        session.add(
            Chapter(
                novel_id=novel.id,
                index=1,
                title="第一章",
                content="已写一段",
                char_count=4,
                status="raw",
                is_generated=True,
                outline_item_id=item.id,
            )
        )
        await session.commit()
        novel_id = novel.id

    payload = (await client.get(f"/api/novels/{novel_id}/backup")).content
    _manifest, tables = _unzip(payload)
    assert tables["rows/novels.json"][0]["status"] == "generating"
    assert tables["rows/outline_items.json"][0]["status"] == "generating"

    restored = await _restore(client, payload)
    assert restored.status_code == 200
    body = restored.json()
    assert body["status"] == "ready"
    copy_id = body["id"]

    async with db_mod.SessionLocal() as session:
        original = await session.get(Novel, novel_id)
        assert original is not None and original.status == "generating"
        original_item = await session.scalar(
            select(OutlineItem)
            .join(Outline, OutlineItem.outline_id == Outline.id)
            .where(Outline.novel_id == novel_id)
        )
        assert original_item is not None and original_item.status == "generating"
        copied = await session.scalar(
            select(OutlineItem)
            .join(Outline, OutlineItem.outline_id == Outline.id)
            .where(Outline.novel_id == copy_id)
        )
        assert copied is not None and copied.status == "pending"
        copied_chapter = await session.scalar(select(Chapter).where(Chapter.novel_id == copy_id))
        assert copied_chapter is not None and copied_chapter.content == "已写一段"


@pytest.mark.asyncio
async def test_backup_missing_novel(client):
    response = await client.get("/api/novels/99999/backup")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_restore_minimal_backup_and_reject_bad_archives(client):
    novel = {"id": 1, "title": "甲"}
    minimal = _zip({"novels": [novel]})
    created = await _restore(client, minimal)
    assert created.status_code == 200
    assert created.json()["title"] == "甲"
    assert created.json()["role"] == "manuscript"
    assert created.json()["origin"] == "import"
    assert created.json()["status"] == "imported"
    assert created.json()["genre"] == "玄幻"

    cases = [
        (b"not-a-zip", None),
        (_zip({"novels": [novel]}, version=2), "版本"),
        (_zip({"novels": [novel]}, extra={"../evil.json": b"{}"}), "未允许"),
        (_zip({"novels": [novel]}, extra={"rows/async_tasks.json": b"[]"}), "未允许"),
        (_zip({"novels": [novel, {"id": 2, "title": "乙"}]}), "一本"),
        (_zip({"novels": [{"id": 1, "title": "甲", "role": "nope"}]}), "role"),
        (
            _zip(
                {
                    "novels": [novel],
                    "chapters": [
                        {"id": 5, "novel_id": 1, "index": 1},
                        {"id": 6, "novel_id": 1, "index": 1},
                    ],
                }
            ),
            "序号",
        ),
        (
            _zip(
                {
                    "novels": [novel],
                    "chapters": [{"id": 5, "novel_id": 9, "index": 1}],
                }
            ),
            "不属于",
        ),
        (
            _zip(
                {
                    "novels": [novel],
                    "chapters": [{"id": 5, "novel_id": 1, "index": 1, "outline_item_id": 99}],
                }
            ),
            "不存在",
        ),
        (
            _zip(
                {
                    "novels": [novel],
                    "chapters": [{"id": 8, "novel_id": 1, "index": 1}],
                    "chapter_versions": [
                        {
                            "id": 1,
                            "chapter_id": 8,
                            "version_type": "generated",
                            "content": "a",
                            "parent_version_id": 2,
                        },
                        {
                            "id": 2,
                            "chapter_id": 8,
                            "version_type": "user_edited",
                            "content": "b",
                            "parent_version_id": 1,
                        },
                    ],
                }
            ),
            "成环",
        ),
        (_zip({"novels": [novel]}, counts={"novels": 9}), "行数"),
    ]
    for payload, needle in cases:
        response = await _restore(client, payload)
        assert response.status_code == 400, response.text
        if needle:
            assert needle in response.json()["detail"]

    listed = await client.get("/api/novels")
    assert len(listed.json()) == 1


@pytest.mark.asyncio
async def test_restore_rejects_oversize_zip(client, monkeypatch):
    monkeypatch.setattr("app.services.novel_backup.MAX_ZIP_BYTES", 40)
    payload = _zip({"novels": [{"id": 1, "title": "这本备份故意写长一点"}]})
    assert len(payload) > 40
    response = await _restore(client, payload)
    assert response.status_code == 413
    listed = await client.get("/api/novels")
    assert listed.json() == []
