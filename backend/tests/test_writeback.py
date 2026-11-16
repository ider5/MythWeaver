"""写后 Story Bible 提案：只列出差异，确认后才写入。"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.db import close_db, init_db
from app.main import create_app
from app.models import Chapter, Novel
from app.services.ingestion import _extract_chapter, incremental_update_chapter
from app.services.writeback import build_writeback_changes
import app.db as db_mod


def test_build_writeback_skips_noop_and_appearance_only():
    characters = [
        {
            "id": 1,
            "name": "叶凡",
            "aliases": ["少年"],
            "role": "主角",
            "status": "凡人",
            "personality": "沉静",
            "speech_style": None,
            "last_appear_chapter": 1,
        }
    ]
    worlds = [{"id": 2, "title": "青阳城", "category": "地理", "content": "边陲城池", "do_not_violate": None}]
    threads = [
        {
            "id": 3,
            "title": "玉佩之谜",
            "description": "发热",
            "thread_type": "伏笔",
            "status": "未回收",
            "introduced_chapter": 1,
            "resolved_chapter": None,
        }
    ]
    same = {
        "characters": [{"name": "叶凡", "aliases": ["少年"], "role": "主角", "status": "凡人", "personality": "沉静"}],
        "world_settings": [{"title": "青阳城", "category": "地理", "content": "边陲城池"}],
        "plot_threads": [{"title": "玉佩之谜", "description": "发热", "thread_type": "伏笔", "status": "未回收"}],
    }
    assert build_writeback_changes(characters, worlds, threads, same, chapter_index=4) == []


def test_build_writeback_updates_alias_match_and_resolves_thread():
    characters = [
        {
            "id": 7,
            "name": "叶凡",
            "aliases": ["少年"],
            "role": "主角",
            "status": "凡人",
            "personality": None,
            "speech_style": None,
            "last_appear_chapter": 1,
        }
    ]
    changes = build_writeback_changes(
        characters,
        [],
        [],
        {
            "characters": [{"name": "少年", "aliases": ["叶小凡"], "status": "筑基"}],
            "world_settings": [{"title": "", "content": "城门日落关闭", "category": "规则"}],
            "plot_threads": [
                {"title": "玉佩之谜", "description": "玉佩认主", "thread_type": "伏笔", "status": "已回收"}
            ],
        },
        chapter_index=4,
    )
    by_kind = {item["kind"]: item for item in changes}
    assert set(by_kind) == {"character", "world", "thread"}

    character = by_kind["character"]
    assert character["op"] == "update"
    assert character["target_id"] == 7
    assert character["label"] == "叶凡"
    assert character["after"]["aliases"] == ["少年", "叶小凡"]
    assert character["after"]["status"] == "筑基"
    assert character["after"]["last_appear_chapter"] == 4

    world = by_kind["world"]
    assert world["op"] == "create"
    assert world["label"] == "城门日落关闭"
    assert world["after"]["content"] == "城门日落关闭"

    thread = by_kind["thread"]
    assert thread["op"] == "create"
    assert thread["summary"].startswith("回收伏笔")
    assert thread["after"]["resolved_chapter"] == 4
    assert thread["after"]["introduced_chapter"] == 4


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    db_path = tmp_path / "writeback.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    get_settings.cache_clear()

    import app.llm.client as llm_mod
    import app.services.tasks as tasks_mod

    db_mod.engine = None
    db_mod.SessionLocal = None
    tasks_mod._queue = None
    llm_mod._client = None
    await init_db()
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await close_db()
    get_settings.cache_clear()
    tasks_mod._queue = None
    llm_mod._client = None
    db_mod.engine = None
    db_mod.SessionLocal = None


async def _add_chapter(session, novel_id: int, *, index: int, content: str, generated: bool) -> int:
    chapter = Chapter(
        novel_id=novel_id,
        index=index,
        title=f"第{index}章",
        content=content,
        char_count=len(content),
        status="raw",
        is_generated=generated,
    )
    session.add(chapter)
    await session.commit()
    await session.refresh(chapter)
    return chapter.id


@pytest.mark.asyncio
async def test_propose_apply_subset_then_reuse_hash(client, monkeypatch):
    calls = {"n": 0}

    async def fake_extract(session, novel_id, chapter):
        calls["n"] += 1
        return {
            "characters": [{"name": "少年", "aliases": ["叶小凡"], "role": "主角", "status": "筑基"}],
            "world_settings": [{"category": "地理", "title": "青阳城", "content": "边陲城池"}],
            "plot_threads": [
                {"title": "玉佩之谜", "description": "玉佩认主", "thread_type": "伏笔", "status": "已回收"}
            ],
        }

    monkeypatch.setattr("app.services.writeback.extract_bible_payload", fake_extract)

    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="回写", genre="玄幻", status="ready", chapter_count=3)
        session.add(novel)
        await session.commit()
        novel_id = novel.id
        chapter_id = await _add_chapter(session, novel_id, index=4, content="叶凡踏入青阳城。", generated=True)

    created = await client.post(
        f"/api/novels/{novel_id}/bible/characters",
        json={"name": "叶凡", "aliases": ["少年"], "role": "主角", "status": "凡人"},
    )
    assert created.status_code == 200

    missing = await client.post(
        f"/api/novels/{novel_id}/bible/proposals",
        json={"chapter_id": 99999},
    )
    assert missing.status_code == 404

    proposed = await client.post(
        f"/api/novels/{novel_id}/bible/proposals",
        json={"chapter_id": chapter_id},
    )
    assert proposed.status_code == 200, proposed.text
    body = proposed.json()
    assert body["status"] == "pending"
    assert body["chapter_index"] == 4
    proposal_id = body["id"]
    kinds = {item["kind"]: item for item in body["changes"]}
    assert kinds["character"]["op"] == "update"
    assert kinds["world"]["op"] == "create"
    assert kinds["thread"]["after"]["resolved_chapter"] == 4

    again = await client.post(
        f"/api/novels/{novel_id}/bible/proposals",
        json={"chapter_id": chapter_id},
    )
    assert again.status_code == 200
    assert again.json()["id"] == proposal_id
    assert calls["n"] == 1

    unknown = await client.post(
        f"/api/novels/{novel_id}/bible/proposals/{proposal_id}/apply",
        json={"change_ids": ["character:不存在"]},
    )
    assert unknown.status_code == 400

    applied = await client.post(
        f"/api/novels/{novel_id}/bible/proposals/{proposal_id}/apply",
        json={"change_ids": [kinds["character"]["id"]]},
    )
    assert applied.status_code == 200
    assert applied.json()["status"] == "applied"

    bible = (await client.get(f"/api/novels/{novel_id}/bible")).json()
    assert bible["characters"][0]["status"] == "筑基"
    assert "叶小凡" in bible["characters"][0]["aliases"]
    assert bible["world_settings"] == []
    assert bible["plot_threads"] == []

    repeat = await client.post(
        f"/api/novels/{novel_id}/bible/proposals/{proposal_id}/apply",
        json={"change_ids": [kinds["character"]["id"]]},
    )
    assert repeat.status_code == 409

    reused = await client.post(
        f"/api/novels/{novel_id}/bible/proposals",
        json={"chapter_id": chapter_id},
    )
    assert reused.json()["id"] == proposal_id
    assert reused.json()["status"] == "applied"
    assert calls["n"] == 1

    forced = await client.post(
        f"/api/novels/{novel_id}/bible/proposals",
        json={"chapter_id": chapter_id, "force": True},
    )
    assert forced.status_code == 200
    forced_body = forced.json()
    assert forced_body["id"] != proposal_id
    assert forced_body["status"] == "pending"
    assert calls["n"] == 2
    forced_kinds = {item["kind"] for item in forced_body["changes"]}
    assert "character" not in forced_kinds
    assert forced_kinds == {"world", "thread"}

    all_applied = await client.post(
        f"/api/novels/{novel_id}/bible/proposals/{forced_body['id']}/apply",
        json={},
    )
    assert all_applied.status_code == 200
    bible = (await client.get(f"/api/novels/{novel_id}/bible")).json()
    assert bible["world_settings"][0]["title"] == "青阳城"
    assert bible["plot_threads"][0]["status"] == "已回收"
    assert bible["plot_threads"][0]["resolved_chapter"] == 4
    assert (await client.get(f"/api/novels/{novel_id}/bible/proposals")).json() == []


@pytest.mark.asyncio
async def test_dismiss_empty_proposal(client, monkeypatch):
    async def empty_extract(session, novel_id, chapter):
        return {}

    monkeypatch.setattr("app.services.writeback.extract_bible_payload", empty_extract)
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="空白", genre="都市", status="ready")
        session.add(novel)
        await session.commit()
        novel_id = novel.id
        chapter_id = await _add_chapter(session, novel_id, index=1, content="无新设定。", generated=True)

    proposed = await client.post(
        f"/api/novels/{novel_id}/bible/proposals",
        json={"chapter_id": chapter_id},
    )
    assert proposed.status_code == 200
    body = proposed.json()
    assert body["changes"] == []
    listed = await client.get(f"/api/novels/{novel_id}/bible/proposals")
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [body["id"]]

    empty_apply = await client.post(
        f"/api/novels/{novel_id}/bible/proposals/{body['id']}/apply",
        json={},
    )
    assert empty_apply.status_code == 400

    dismissed = await client.post(f"/api/novels/{novel_id}/bible/proposals/{body['id']}/dismiss")
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "dismissed"
    assert (await client.get(f"/api/novels/{novel_id}/bible/proposals")).json() == []
    again = await client.post(f"/api/novels/{novel_id}/bible/proposals/{body['id']}/dismiss")
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_generated_incremental_does_not_merge_and_reuses_proposal(client, monkeypatch):
    calls = {"n": 0}

    async def fake_extract(session, novel_id, chapter):
        calls["n"] += 1
        return {
            "characters": [{"name": "阿宁", "role": "配角", "status": "在城门"}],
            "world_settings": [],
            "plot_threads": [],
        }

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.writeback.extract_bible_payload", fake_extract)
    monkeypatch.setattr("app.services.ingestion._summarize_chapter", noop)
    monkeypatch.setattr("app.services.ingestion.embed_and_store", noop)

    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="生成章", genre="玄幻", status="ready")
        session.add(novel)
        await session.commit()
        await session.refresh(novel)
        chapter = Chapter(
            novel_id=novel.id,
            index=2,
            title="第二章",
            content="阿宁站在城门口。",
            char_count=8,
            status="raw",
            is_generated=True,
        )
        session.add(chapter)
        await session.commit()
        await session.refresh(chapter)
        novel_id = novel.id
        await incremental_update_chapter(session, chapter)
        await incremental_update_chapter(session, chapter)

    assert calls["n"] == 1
    bible = (await client.get(f"/api/novels/{novel_id}/bible")).json()
    assert bible["characters"] == []
    proposals = (await client.get(f"/api/novels/{novel_id}/bible/proposals")).json()
    assert len(proposals) == 1
    assert proposals[0]["changes"][0]["label"] == "阿宁"
    assert proposals[0]["changes"][0]["op"] == "create"


@pytest.mark.asyncio
async def test_manuscript_extract_still_merges(client, monkeypatch):
    async def fake_extract(session, novel_id, chapter):
        return {
            "characters": [{"name": "阿宁", "role": "配角"}],
            "world_settings": [],
            "plot_threads": [],
        }

    monkeypatch.setattr("app.services.writeback.extract_bible_payload", fake_extract)
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="原稿", genre="玄幻", status="ready")
        session.add(novel)
        await session.commit()
        await session.refresh(novel)
        chapter = Chapter(
            novel_id=novel.id,
            index=1,
            title="第一章",
            content="阿宁出现了。",
            char_count=6,
            status="raw",
            is_generated=False,
        )
        session.add(chapter)
        await session.commit()
        await session.refresh(chapter)
        await _extract_chapter(session, novel, chapter)
        await session.commit()
        novel_id = novel.id

    bible = (await client.get(f"/api/novels/{novel_id}/bible")).json()
    assert [row["name"] for row in bible["characters"]] == ["阿宁"]
    assert (await client.get(f"/api/novels/{novel_id}/bible/proposals")).json() == []
