"""生成章节 upsert：已有同 index 的 raw 章时覆盖更新，不触发 UNIQUE。"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.config import get_settings
from app.db import close_db, init_db
from app.llm.client import MockLLMClient, set_llm_client
from app.models import Chapter, ChapterVersion, Novel, Outline, OutlineItem
from app.services.generation import resolve_target_chapter_index, stream_generate_chapter
import app.db as db_mod


@pytest_asyncio.fixture
async def db_ready(tmp_path, monkeypatch):
    db_path = tmp_path / "gen_upsert.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("EMBEDDING_DIMS", "8")
    get_settings.cache_clear()

    import app.llm.client as llm_mod

    db_mod.engine = None
    db_mod.SessionLocal = None
    llm_mod._client = None

    set_llm_client(
        MockLLMClient(
            stream_text="第四十章：白发鬼手\n叶凡踏入秘境，白发鬼手自雾中伸出。",
            embed_dim=8,
            smart=True,
        )
    )
    await init_db()
    yield
    await close_db()
    get_settings.cache_clear()
    llm_mod._client = None
    db_mod.engine = None
    db_mod.SessionLocal = None


def test_resolve_target_chapter_index_from_outline_order():
    assert resolve_target_chapter_index(start_from_chapter=40, order=1) == 40
    assert resolve_target_chapter_index(start_from_chapter=40, order=2) == 41
    assert resolve_target_chapter_index(start_from_chapter=1, order=1) == 1


@pytest.mark.asyncio
async def test_regenerate_existing_raw_chapter_updates_not_insert(db_ready):
    """chapter_count 未确认、index=40 已有 raw 行时再次生成应覆盖，不 UNIQUE。"""
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(
            title="试炼",
            genre="玄幻",
            status="ready",
            chapter_count=39,  # 未确认入库时可能仍停在 39
        )
        session.add(novel)
        await session.flush()

        outline = Outline(
            novel_id=novel.id,
            title="续写大纲",
            status="confirmed",
            start_from_chapter=40,
        )
        session.add(outline)
        await session.flush()

        item = OutlineItem(
            outline_id=outline.id,
            order=1,
            title="第四十章：白发鬼手",
            summary="秘境遇白发鬼手",
            key_points=["白发鬼手"],
            status="pending",
        )
        session.add(item)
        await session.flush()

        existing = Chapter(
            novel_id=novel.id,
            index=40,
            title="第四十章：白发鬼手",
            content="（上次中断留下的草稿）",
            char_count=10,
            status="raw",
            is_generated=True,
            outline_item_id=item.id,
        )
        session.add(existing)
        await session.flush()
        old_id = existing.id
        session.add(
            ChapterVersion(
                chapter_id=existing.id,
                version_type="generated",
                content=existing.content,
            )
        )
        await session.commit()
        novel_id = novel.id
        item_id = item.id

    async with db_mod.SessionLocal() as session:
        events = []
        async for evt in stream_generate_chapter(
            session,
            novel_id,
            item_id,
            run_critic=False,
            max_critic_rounds=0,
        ):
            events.append(evt)

    assert not any(e.get("event") == "error" for e in events), events
    done = next(e for e in events if e.get("event") == "done")
    assert done["chapter_id"] == old_id
    assert "白发鬼手" in (done.get("content") or "")
    assert done.get("overwritten") is True

    async with db_mod.SessionLocal() as session:
        count = await session.scalar(
            select(func.count()).select_from(Chapter).where(
                Chapter.novel_id == novel_id, Chapter.index == 40
            )
        )
        assert count == 1
        chapter = await session.get(Chapter, old_id)
        assert chapter is not None
        assert chapter.index == 40
        assert "秘境" in chapter.content
        assert chapter.outline_item_id == item_id
        assert chapter.status == "raw"
        assert chapter.is_generated is True
        versions = (
            await session.execute(
                select(ChapterVersion)
                .where(ChapterVersion.chapter_id == old_id)
                .order_by(ChapterVersion.id)
            )
        ).scalars().all()
        assert len(versions) >= 2
        assert versions[-1].version_type == "generated"
        assert "秘境" in versions[-1].content


@pytest.mark.asyncio
async def test_critic_off_leaves_generated_without_report(db_ready):
    """关闭一致性检验时，generated 版本不应有 consistency_report。"""
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="无报告", genre="玄幻", status="ready", chapter_count=0)
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
            summary="开篇",
            key_points=[],
            status="pending",
        )
        session.add(item)
        await session.commit()
        novel_id, item_id = novel.id, item.id

    async with db_mod.SessionLocal() as session:
        events = [
            e
            async for e in stream_generate_chapter(
                session, novel_id, item_id, run_critic=False, max_critic_rounds=0
            )
        ]
    assert not any(e.get("event") == "error" for e in events), events
    done = next(e for e in events if e.get("event") == "done")
    assert done.get("consistency") is None

    async with db_mod.SessionLocal() as session:
        versions = (
            await session.execute(
                select(ChapterVersion)
                .where(ChapterVersion.chapter_id == done["chapter_id"])
                .order_by(ChapterVersion.id)
            )
        ).scalars().all()
        assert len(versions) == 1
        assert versions[0].version_type == "generated"
        assert versions[0].consistency_report is None


@pytest.mark.asyncio
async def test_overwrite_with_critic_binds_report_to_latest_generated(db_ready):
    """覆盖生成且检验开启、无需改写时：最新 generated 应有报告，旧版保持原样。"""
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="覆盖报告", genre="玄幻", status="ready", chapter_count=0)
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
            summary="开篇",
            key_points=[],
            status="pending",
        )
        session.add(item)
        await session.flush()
        ch = Chapter(
            novel_id=novel.id,
            index=1,
            title="第一章",
            content="旧草稿",
            char_count=3,
            status="raw",
            is_generated=True,
            outline_item_id=item.id,
        )
        session.add(ch)
        await session.flush()
        session.add(
            ChapterVersion(
                chapter_id=ch.id,
                version_type="generated",
                content="旧草稿",
                consistency_report=None,
            )
        )
        await session.commit()
        novel_id, item_id, chapter_id = novel.id, item.id, ch.id

    async with db_mod.SessionLocal() as session:
        events = [
            e
            async for e in stream_generate_chapter(
                session, novel_id, item_id, run_critic=True, max_critic_rounds=0
            )
        ]
    assert not any(e.get("event") == "error" for e in events), events
    done = next(e for e in events if e.get("event") == "done")
    assert done.get("overwritten") is True
    assert done.get("consistency") is not None
    assert done["consistency"]["ok"] is True

    async with db_mod.SessionLocal() as session:
        versions = (
            await session.execute(
                select(ChapterVersion)
                .where(ChapterVersion.chapter_id == chapter_id)
                .order_by(ChapterVersion.id)
            )
        ).scalars().all()
        assert len(versions) == 2
        assert versions[0].consistency_report is None
        assert versions[1].version_type == "generated"
        assert versions[1].id == done["version_id"]
        assert versions[1].consistency_report is not None
        assert versions[1].consistency_report["ok"] is True
        assert versions[1].consistency_report["critic_rounds"] == 0


@pytest.mark.asyncio
async def test_critic_revise_binds_initial_and_final_reports(db_ready, monkeypatch):
    """有改写时：generated 存初检，critic_revised 存终检。"""
    from app.schemas.generation import ConsistencyIssue, ConsistencyReport
    from app.services import consistency as cons_mod

    assert db_mod.SessionLocal is not None

    call_n = {"n": 0}

    async def fake_check(session, novel, content, *, recent_tail=""):
        call_n["n"] += 1
        if "上一章" in (content or ""):
            return ConsistencyReport(
                ok=False,
                issues=[
                    ConsistencyIssue(
                        type="chapter_meta",
                        severity="error",
                        message="正文出现章号/章节元指称",
                    )
                ],
                critic_rounds=0,
            )
        return ConsistencyReport(ok=True, issues=[], critic_rounds=0)

    async def fake_revise(session, novel, content, report):
        fixed = (content or "").replace("上一章", "此前")
        new_report = await fake_check(session, novel, fixed)
        new_report.critic_rounds = report.critic_rounds + 1
        return fixed, new_report

    monkeypatch.setattr(cons_mod, "check_consistency", fake_check)
    monkeypatch.setattr(cons_mod, "critic_revise", fake_revise)

    set_llm_client(
        MockLLMClient(
            stream_text="叶凡想起上一章的遭遇，继续前行。",
            embed_dim=8,
            smart=True,
        )
    )

    async with db_mod.SessionLocal() as session:
        novel = Novel(title="改写报告", genre="玄幻", status="ready", chapter_count=0)
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
            summary="开篇",
            key_points=[],
            status="pending",
        )
        session.add(item)
        await session.commit()
        novel_id, item_id = novel.id, item.id

    async with db_mod.SessionLocal() as session:
        events = [
            e
            async for e in stream_generate_chapter(
                session, novel_id, item_id, run_critic=True, max_critic_rounds=1
            )
        ]
    assert not any(e.get("event") == "error" for e in events), events
    done = next(e for e in events if e.get("event") == "done")
    assert done["consistency"]["ok"] is True
    assert done["consistency"]["critic_rounds"] == 1

    async with db_mod.SessionLocal() as session:
        versions = (
            await session.execute(
                select(ChapterVersion)
                .where(ChapterVersion.chapter_id == done["chapter_id"])
                .order_by(ChapterVersion.id)
            )
        ).scalars().all()
        assert len(versions) == 2
        draft, revised = versions
        assert draft.version_type == "generated"
        assert draft.consistency_report is not None
        assert draft.consistency_report["ok"] is False
        assert draft.consistency_report["critic_rounds"] == 0
        assert "上一章" in draft.content

        assert revised.version_type == "critic_revised"
        assert revised.id == done["version_id"]
        assert revised.parent_version_id == draft.id
        assert revised.consistency_report is not None
        assert revised.consistency_report["ok"] is True
        assert revised.consistency_report["critic_rounds"] == 1
        assert "上一章" not in revised.content
        assert "此前" in revised.content
