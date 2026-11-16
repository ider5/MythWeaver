"""勾选 Critic 问题 → 预览修稿 → 确认写入。"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import get_settings
from app.db import close_db, init_db
from app.llm.client import MockLLMClient, set_llm_client
from app.main import create_app
from app.models import Chapter, ChapterVersion, Novel
from app.schemas.generation import ConsistencyIssue
from app.services.consistency import critic_revise_selected
import app.db as db_mod


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    db_path = tmp_path / "critic_sel.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("EMBEDDING_DIMS", "8")
    monkeypatch.setenv("AGENT_RUNTIME", "legacy")
    get_settings.cache_clear()

    import app.llm.client as llm_mod
    import app.services.tasks as tasks_mod

    tasks_mod._queue = None
    llm_mod._client = None
    db_mod.engine = None
    db_mod.SessionLocal = None

    set_llm_client(MockLLMClient(stream_text="修好后的正文不含套话", embed_dim=8, smart=True))
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


async def _seed() -> tuple[int, int]:
    assert db_mod.SessionLocal
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="勾选修", genre="玄幻", status="ready", chapter_count=1, total_chars=10)
        session.add(novel)
        await session.flush()
        ch = Chapter(
            novel_id=novel.id,
            index=1,
            title="第一章",
            content="作为AI，我认为本章总结如下。",
            char_count=20,
            status="embedded",
            is_generated=True,
        )
        session.add(ch)
        await session.flush()
        ver = ChapterVersion(
            chapter_id=ch.id,
            version_type="generated",
            content=ch.content,
            consistency_report={
                "ok": False,
                "issues": [
                    {
                        "type": "ai_voice",
                        "severity": "warning",
                        "message": "套话",
                        "detail": None,
                    }
                ],
                "critic_rounds": 1,
            },
        )
        session.add(ver)
        await session.commit()
        return novel.id, ch.id


@pytest.mark.asyncio
async def test_critic_select_preview_and_confirm(client: AsyncClient):
    nid, cid = await _seed()
    preview = await client.post(
        f"/api/novels/{nid}/chapters/{cid}/critic-select-revise",
        json={
            "content": "作为AI，我认为本章总结如下。",
            "issues": [{"type": "ai_voice", "severity": "warning", "message": "套话"}],
            "confirm": False,
        },
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["changed"] is True
    assert body["version_id"] is None
    assert "修好" in body["revised_content"] or body["revised_content"] != body["base_content"]

    confirm = await client.post(
        f"/api/novels/{nid}/chapters/{cid}/critic-select-revise",
        json={
            "content": body["base_content"],
            "issues": [{"type": "ai_voice", "severity": "warning", "message": "套话"}],
            "confirm": True,
            "commit_to_knowledge": False,
        },
    )
    assert confirm.status_code == 200, confirm.text
    out = confirm.json()
    assert out["version_id"] is not None
    assert out["changed"] is True

    assert db_mod.SessionLocal
    async with db_mod.SessionLocal() as session:
        vers = (
            await session.execute(select(ChapterVersion).where(ChapterVersion.chapter_id == cid))
        ).scalars().all()
        assert any(v.version_type == "user_edited" for v in vers)


@pytest.mark.asyncio
async def test_critic_revise_selected_empty_noop(client: AsyncClient):
    nid, cid = await _seed()
    assert db_mod.SessionLocal
    async with db_mod.SessionLocal() as session:
        novel = await session.get(Novel, nid)
        text, report = await critic_revise_selected(
            session,
            novel,
            "原文",
            [ConsistencyIssue(type="x", severity="info", message="仅提示")],
        )
        assert text == "原文"
        assert report.ok is True
