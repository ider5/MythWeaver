"""大纲蓝图字段：schema 往返、生成/更新，以及续写提示消费。"""

from __future__ import annotations

import json
import sqlite3

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.db import close_db, init_db
from app.llm.client import MockLLMClient, get_llm_client, set_llm_client
from app.llm.prompts import render
from app.main import create_app
from app.models import Novel, Outline, OutlineItem
from app.schemas.outline import OutlineItemOut
from app.services.context_builder import outline_item_query
from app.services.generation import stream_generate_chapter
from app.services.outline import blueprint_from_raw, normalize_outline_items
from app.services.tasks import get_task_queue
import app.db as db_mod


def _reset_runtime() -> None:
    import app.llm.client as llm_mod
    import app.services.tasks as tasks_mod

    db_mod.engine = None
    db_mod.SessionLocal = None
    llm_mod._client = None
    tasks_mod._queue = None


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    db_path = tmp_path / "outline_bp.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("EMBEDDING_DIMS", "8")
    get_settings.cache_clear()
    _reset_runtime()
    set_llm_client(MockLLMClient(embed_dim=8, smart=True))
    await init_db()
    from app.services.outline import outline_generate_handler

    get_task_queue().register("outline_generate", outline_generate_handler)
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await close_db()
    get_settings.cache_clear()
    _reset_runtime()


def test_normalize_keeps_legacy_fields_and_blueprint_aliases():
    raw = [
        {
            "order": 9,
            "title": "第三章：旧标题",
            "summary": "旧概要",
            "key_points": ["要点"],
            "goal": "拿到地图",
            "keyEvents": "傀儡拦路，玉佩反噬",
            "suspenseHook": "背面是苏婉",
            "characters": "叶凡、守门傀儡",
        }
    ]
    items = normalize_outline_items(raw, start_from_chapter=40)
    assert items[0]["title"] == "第四十章：旧标题"
    assert items[0]["summary"] == "旧概要"
    assert items[0]["key_points"] == ["要点"]
    assert items[0]["purpose"] == "拿到地图"
    assert items[0]["conflict"] == "傀儡拦路，玉佩反噬"
    assert items[0]["suspense_hook"] == "背面是苏婉"
    assert items[0]["characters"] == ["叶凡", "守门傀儡"]


def test_blueprint_from_raw_accepts_name_objects_and_blanks():
    fields = blueprint_from_raw(
        {
            "summary": "只改概要时蓝图仍可缺省",
            "characters": [{"name": "叶凡"}, {"name": "苏婉"}, "叶凡"],
        }
    )
    assert fields == {
        "purpose": "",
        "conflict": "",
        "suspense_hook": "",
        "characters": ["叶凡", "苏婉"],
    }


def test_outline_item_out_round_trips_legacy_row():
    item = OutlineItem(
        id=1,
        outline_id=1,
        order=1,
        title="旧章",
        summary="旧摘要",
        key_points=["要点"],
        status="pending",
    )
    out = OutlineItemOut.model_validate(item)
    assert out.title == "旧章"
    assert out.summary == "旧摘要"
    assert out.key_points == ["要点"]
    assert out.purpose == ""
    assert out.conflict == ""
    assert out.suspense_hook == ""
    assert out.characters == []


def test_outline_item_query_includes_blueprint():
    item = OutlineItem(
        outline_id=1,
        order=1,
        title="第四十章：秘境",
        summary="叶凡进入秘境",
        key_points=["遇怪"],
        purpose="拿到地图",
        conflict="傀儡拦路",
        suspense_hook="背面是苏婉",
        characters=["叶凡", "苏婉"],
    )
    query = outline_item_query(item)
    assert "叶凡进入秘境" in query
    assert "拿到地图" in query
    assert "傀儡拦路" in query
    assert "背面是苏婉" in query
    assert "遇怪" in query
    assert "叶凡" in query and "苏婉" in query


def test_generation_prompt_includes_blueprint_fields():
    text = render(
        "generation.j2",
        genre="玄幻",
        genre_hints="",
        story_bible="（空）",
        memory="（空）",
        style_samples="（无）",
        summaries="（无）",
        rag_context="（无）",
        recent_chapters="（无）",
        chapter_title="第四十章：秘境",
        chapter_summary="叶凡进入秘境",
        key_points=["遇怪"],
        target_chars=3000,
        chapter_purpose="拿到地图",
        chapter_conflict="傀儡拦路",
        chapter_suspense="背面是苏婉",
        chapter_characters=["叶凡", "苏婉"],
    )
    assert "主角小目标：拿到地图" in text
    assert "冲突与转折：傀儡拦路" in text
    assert "悬念钩子：背面是苏婉" in text
    assert "出场人物：叶凡、苏婉" in text
    assert "落实以上蓝图" in text


def test_generation_prompt_omits_empty_blueprint():
    text = render(
        "generation.j2",
        genre="玄幻",
        genre_hints="",
        story_bible="（空）",
        memory="（空）",
        style_samples="（无）",
        summaries="（无）",
        rag_context="（无）",
        recent_chapters="（无）",
        chapter_title="第四十章",
        chapter_summary="试炼",
        key_points=["遇怪"],
        target_chars=3000,
        chapter_purpose="",
        chapter_conflict="",
        chapter_suspense="",
        chapter_characters=[],
    )
    assert "主角小目标：" not in text
    assert "落实以上蓝图" not in text
    assert "概要：试炼" in text


@pytest.mark.asyncio
async def test_outline_put_round_trips_blueprint_and_keeps_omitted_fields(client):
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="蓝图", genre="玄幻", status="ready", chapter_count=1)
        session.add(novel)
        await session.flush()
        outline = Outline(
            novel_id=novel.id, title="续写", status="draft", start_from_chapter=2
        )
        session.add(outline)
        await session.flush()
        item = OutlineItem(
            outline_id=outline.id,
            order=1,
            title="第二章",
            summary="旧摘要",
            key_points=["旧"],
            status="pending",
        )
        session.add(item)
        await session.commit()
        novel_id, oid, item_id = novel.id, outline.id, item.id

    r = await client.get(f"/api/novels/{novel_id}/outlines/{oid}")
    assert r.status_code == 200
    legacy = r.json()["items"][0]
    assert legacy["title"] == "第二章"
    assert legacy["summary"] == "旧摘要"
    assert legacy["key_points"] == ["旧"]
    assert legacy["purpose"] == ""
    assert legacy["conflict"] == ""
    assert legacy["suspense_hook"] == ""
    assert legacy["characters"] == []

    r = await client.put(
        f"/api/novels/{novel_id}/outlines/{oid}",
        json={
            "items": [
                {
                    "id": item_id,
                    "order": 1,
                    "title": "第二章 改名",
                    "summary": "新摘要",
                    "key_points": ["新"],
                    "status": "pending",
                    "purpose": "拿到地图",
                    "conflict": "傀儡拦路",
                    "suspense_hook": "背面是苏婉",
                    "characters": ["叶凡", "苏婉"],
                }
            ]
        },
    )
    assert r.status_code == 200
    saved = r.json()["items"][0]
    assert saved["id"] == item_id
    assert saved["summary"] == "新摘要"
    assert saved["purpose"] == "拿到地图"
    assert saved["conflict"] == "傀儡拦路"
    assert saved["suspense_hook"] == "背面是苏婉"
    assert saved["characters"] == ["叶凡", "苏婉"]

    r = await client.put(
        f"/api/novels/{novel_id}/outlines/{oid}",
        json={
            "items": [
                {
                    "id": item_id,
                    "order": 1,
                    "title": "第二章 再改",
                    "summary": "只改概要",
                    "key_points": ["仍在"],
                    "status": "pending",
                }
            ]
        },
    )
    assert r.status_code == 200
    kept = r.json()["items"][0]
    assert kept["title"] == "第二章 再改"
    assert kept["summary"] == "只改概要"
    assert kept["key_points"] == ["仍在"]
    assert kept["purpose"] == "拿到地图"
    assert kept["conflict"] == "傀儡拦路"
    assert kept["characters"] == ["叶凡", "苏婉"]

    r = await client.put(
        f"/api/novels/{novel_id}/outlines/{oid}",
        json={
            "items": [
                {
                    "id": item_id,
                    "order": 1,
                    "title": "第二章 再改",
                    "summary": "只改概要",
                    "key_points": ["仍在"],
                    "status": "pending",
                    "purpose": "",
                    "characters": [],
                }
            ]
        },
    )
    cleared = r.json()["items"][0]
    assert cleared["purpose"] == ""
    assert cleared["characters"] == []
    assert cleared["conflict"] == "傀儡拦路"
    assert cleared["suspense_hook"] == "背面是苏婉"


@pytest.mark.asyncio
async def test_outline_generate_stores_blueprint_from_mock_llm(client):
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="生成蓝图", genre="玄幻", status="ready", chapter_count=0)
        session.add(novel)
        await session.commit()
        novel_id = novel.id

    payload = {
        "title": "青阳风云",
        "items": [
            {
                "order": 1,
                "title": "第一章：入城",
                "summary": "叶凡抵达青阳",
                "key_points": ["亮玉佩"],
                "goal": "找到苏婉",
                "keyEvents": "城门盘查，玉佩发热",
                "suspenseHook": "苏婉已经不在客栈",
                "cast": ["叶凡", "城门校尉"],
            }
        ],
    }
    set_llm_client(MockLLMClient(embed_dim=8, smart=False, chat_responses=[json.dumps(payload, ensure_ascii=False)]))

    r = await client.post(
        f"/api/novels/{novel_id}/outlines/generate",
        json={"chapter_count": 1, "guidance": "先入城"},
    )
    assert r.status_code == 200
    task_id = r.json()["task_id"]
    await get_task_queue().wait_task(task_id, timeout=60)

    listed = await client.get(f"/api/novels/{novel_id}/outlines")
    assert listed.status_code == 200
    outlines = listed.json()
    assert len(outlines) == 1
    item = outlines[0]["items"][0]
    assert item["summary"] == "叶凡抵达青阳"
    assert item["key_points"] == ["亮玉佩"]
    assert item["purpose"] == "找到苏婉"
    assert item["conflict"] == "城门盘查，玉佩发热"
    assert item["suspense_hook"] == "苏婉已经不在客栈"
    assert item["characters"] == ["叶凡", "城门校尉"]
    assert item["title"].startswith("第一章")


@pytest.mark.asyncio
async def test_confirmed_outline_blueprint_enters_generation_prompt(client):
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="续写蓝图", genre="玄幻", status="ready", chapter_count=0)
        session.add(novel)
        await session.flush()
        outline = Outline(
            novel_id=novel.id, title="已确认", status="confirmed", start_from_chapter=1
        )
        session.add(outline)
        await session.flush()
        item = OutlineItem(
            outline_id=outline.id,
            order=1,
            title="第一章：秘境",
            summary="叶凡进入秘境",
            key_points=["遇怪"],
            purpose="拿到地图",
            conflict="傀儡拦路",
            suspense_hook="背面是苏婉",
            characters=["叶凡", "苏婉"],
            status="pending",
        )
        session.add(item)
        await session.commit()
        novel_id, item_id = novel.id, item.id

    mock = get_llm_client()
    assert isinstance(mock, MockLLMClient)
    mock.stream_calls.clear()
    async with db_mod.SessionLocal() as session:
        events = []
        async for evt in stream_generate_chapter(
            session, novel_id, item_id, run_critic=False, max_critic_rounds=0
        ):
            events.append(evt)
    assert not any(e.get("event") == "error" for e in events), events
    blobs = ["\n".join(m["content"] for m in call["messages"]) for call in mock.stream_calls]
    joined = "\n".join(blobs)
    assert "主角小目标：拿到地图" in joined
    assert "冲突与转折：傀儡拦路" in joined
    assert "悬念钩子：背面是苏婉" in joined
    assert "出场人物：叶凡、苏婉" in joined


@pytest.mark.asyncio
async def test_legacy_outline_items_gain_empty_blueprint_columns(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.db"
    raw = sqlite3.connect(db_path)
    raw.execute(
        """
        CREATE TABLE outline_items (
            id INTEGER PRIMARY KEY,
            outline_id INTEGER NOT NULL,
            "order" INTEGER NOT NULL,
            title VARCHAR(256) DEFAULT '',
            summary TEXT DEFAULT '',
            key_points JSON,
            status VARCHAR(32) DEFAULT 'pending'
        )
        """
    )
    raw.execute(
        """
        INSERT INTO outline_items (outline_id, "order", title, summary, key_points, status)
        VALUES (1, 1, '旧章', '旧摘要', '["旧要点"]', 'pending')
        """
    )
    raw.commit()
    raw.close()

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("EMBEDDING_DIMS", "8")
    get_settings.cache_clear()
    _reset_runtime()
    await init_db()
    try:
        from sqlalchemy import text

        assert db_mod.engine is not None
        async with db_mod.engine.connect() as conn:
            cols = (await conn.execute(text("PRAGMA table_info(outline_items)"))).fetchall()
        names = {row[1] for row in cols}
        assert {"purpose", "conflict", "suspense_hook", "characters"} <= names

        async with db_mod.SessionLocal() as session:
            item = await session.get(OutlineItem, 1)
            assert item is not None
            assert item.title == "旧章"
            assert item.summary == "旧摘要"
            assert item.key_points == ["旧要点"]
            assert item.purpose == ""
            assert item.conflict == ""
            assert item.suspense_hook == ""
            assert item.characters == []
    finally:
        await close_db()
        get_settings.cache_clear()
        _reset_runtime()
