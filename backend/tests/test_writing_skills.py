"""阶段写法：只解析提示词，预览后安装，按阶段注入。"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.db import close_db, init_db
from app.llm.client import MockLLMClient, set_llm_client
from app.llm.prompts import render
from app.main import create_app
from app.models import Novel, Outline, OutlineItem
from app.schemas.generation import ConsistencyIssue, ConsistencyReport
from app.services.consistency import check_consistency, critic_revise
from app.services.generation import stream_generate_chapter
from app.services.outline import generate_outline
from app.services.writing_skills import (
    SKILLS_DIR,
    SkillParseError,
    install_skill,
    load_catalog,
    parse_skill,
    read_catalog_source,
    select_injected,
)
import app.db as db_mod
import app.llm.client as llm_mod
import app.services.writing_skills as skills_mod


def _skill(name: str, stage: str, body: str, description: str = "测试写法") -> str:
    return (
        f"---\nname: {name}\ndescription: {description}\nstage: {stage}\n---\n{body}\n"
    )


def test_parse_keeps_prompt_text():
    parsed = parse_skill(_skill("chapter-hook", "draft", "章末停住。{{ 7*7 }}"))
    assert parsed.name == "chapter-hook"
    assert parsed.stage == "draft"
    assert parsed.body == "章末停住。{{ 7*7 }}"
    assert parsed.stage_label == "正文"


def test_parse_rejects_executable_frontmatter():
    source = "---\nname: run-me\ndescription: 坏示例\nstage: draft\nrun: python evil.py\n---\nhello\n"
    with pytest.raises(SkillParseError) as caught:
        parse_skill(source)
    assert any("不执行" in item for item in caught.value.errors)


@pytest.mark.parametrize(
    "source",
    [
        "---\nname: bad-stage\ndescription: 说明\nstage: publish\n---\n正文\n",
        "---\nname: Bad_Name\ndescription: 说明\nstage: draft\n---\n正文\n",
        "没有 frontmatter\n",
        "---\nname: empty-body\ndescription: 说明\nstage: draft\n---\n",
        "---\nname: script-tag\ndescription: 说明\nstage: draft\n---\n<script>alert(1)</script>\n",
        "---\nname: shebang\ndescription: 说明\nstage: draft\n---\n#!/bin/sh\necho hi\n",
        "---\nname: tools\ndescription: 说明\nstage: critic\nscripts: ./run.sh\n---\n正文\n",
    ],
)
def test_parse_rejects_unsafe_or_incomplete(source: str):
    with pytest.raises(SkillParseError):
        parse_skill(source)


def test_parse_does_not_read_files(monkeypatch):
    calls: list[Path] = []
    real = Path.read_text

    def tracked(self, *args, **kwargs):
        calls.append(self)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", tracked)
    parse_skill(_skill("local-only", "revise", "只改点名的句子"))
    assert calls == []


def test_module_does_not_invoke_code():
    source = inspect.getsource(skills_mod)
    assert "subprocess" not in source
    assert "os.system" not in source
    assert "eval(" not in source
    assert "exec(" not in source


def test_catalog_is_prompt_only_and_covers_stages():
    items = load_catalog()
    stages = {parsed.stage for _cid, parsed in items}
    assert stages == {"outline", "draft", "critic", "revise"}
    for catalog_id, parsed in items:
        assert parsed.name == catalog_id
        assert parsed.body
        assert (SKILLS_DIR / f"{catalog_id}.md").is_file()


@pytest.mark.parametrize(
    "catalog_id",
    ["../entities", "draft-scene-first/../../etc/passwd", "draft-scene-first.md", ""],
)
def test_catalog_id_cannot_escape(catalog_id: str):
    with pytest.raises(SkillParseError):
        read_catalog_source(catalog_id)


def test_skill_body_is_not_rendered_as_template():
    body = "字面量 {{ 7*7 }} 以及 {% include 'anti_ai.j2' %}"
    text = render(
        "generation.j2",
        genre="玄幻",
        genre_hints="",
        story_bible="（空）",
        memory="（空）",
        style_samples="样本",
        summaries="（无）",
        rag_context="（无）",
        recent_chapters="（无）",
        chapter_title="第一章",
        chapter_summary="开篇",
        key_points=["见面"],
        target_chars=3000,
        stage_skills=body,
    )
    assert "{{ 7*7 }}" in text
    assert "{% include 'anti_ai.j2' %}" in text
    assert "字面量 49" not in text
    assert text.count("读者要看到场面") == 1
    assert "已安装的正文写法" in text


def test_missing_stage_skills_leave_prompts_unchanged():
    text = render(
        "outline.j2",
        chapter_count=1,
        genre="玄幻",
        guidance="",
        premise="",
        writing_style="",
        is_scratch=False,
        recent_summaries="（无）",
        story_bible="（空）",
        memory="（无）",
        start_from_chapter=1,
        start_from_chinese="一",
        existing_chapter_count=0,
    )
    assert "已安装的大纲写法" not in text


def test_select_injected_skips_disabled_and_overflow():
    class Row:
        def __init__(self, id, name, body, enabled=True):
            self.id = id
            self.name = name
            self.description = "长"
            self.body = body
            self.enabled = enabled

    rows = [
        Row(1, "off", "甲" * 100, enabled=False),
        Row(2, "first", "甲" * 4000),
        Row(3, "second", "乙" * 4000),
    ]
    chosen = select_injected(rows)
    assert [row.name for row in chosen] == ["first"]


class CaptureClient(MockLLMClient):
    def __init__(self) -> None:
        super().__init__(stream_text="叶凡推开门。", embed_dim=8, smart=True)
        self.chats: list[list[dict]] = []

    async def chat(self, messages, **kwargs):
        self.chats.append(messages)
        return await super().chat(messages, **kwargs)


def _reset_runtime(monkeypatch, tmp_path):
    db_path = tmp_path / "skills.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("EMBEDDING_DIMS", "8")
    get_settings.cache_clear()
    db_mod.engine = None
    db_mod.SessionLocal = None
    llm_mod._client = None
    import app.services.tasks as tasks_mod

    tasks_mod._queue = None


async def _cleanup_runtime():
    await close_db()
    get_settings.cache_clear()
    db_mod.engine = None
    db_mod.SessionLocal = None
    llm_mod._client = None
    import app.services.tasks as tasks_mod

    tasks_mod._queue = None


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    _reset_runtime(monkeypatch, tmp_path)
    set_llm_client(MockLLMClient(embed_dim=8, smart=True))
    await init_db()
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await _cleanup_runtime()


@pytest_asyncio.fixture
async def capture(tmp_path, monkeypatch):
    _reset_runtime(monkeypatch, tmp_path)
    client = CaptureClient()
    set_llm_client(client)
    await init_db()
    yield client
    await _cleanup_runtime()


@pytest.mark.asyncio
async def test_preview_install_replace_and_catalog(client: AsyncClient):
    source = _skill("chapter-hook", "draft", "章末停在未完成的动作上。")
    preview = await client.post("/api/skills/preview", json={"source": source})
    assert preview.status_code == 200
    body = preview.json()
    assert body["ok"] is True
    assert body["stage"] == "draft"
    assert body["body"] == "章末停在未完成的动作上。"
    assert body["already_installed"] is False
    assert (await client.get("/api/skills")).json() == []

    rejected = await client.post(
        "/api/skills",
        json={
            "source": "---\nname: run-me\ndescription: 坏\nstage: draft\nrun: python evil.py\n---\nhello\n"
        },
    )
    assert rejected.status_code == 400
    assert any("不执行" in item for item in rejected.json()["detail"])
    assert (await client.get("/api/skills")).json() == []

    escaped = await client.post("/api/skills/preview", json={"catalog_id": "../entities"})
    assert escaped.json()["ok"] is False
    missing = await client.post("/api/skills", json={"catalog_id": "../../etc/passwd"})
    assert missing.status_code == 400

    both = await client.post(
        "/api/skills/preview",
        json={"source": source, "catalog_id": "draft-scene-first"},
    )
    assert both.status_code == 422

    created = await client.post("/api/skills", json={"source": source})
    assert created.status_code == 200
    installed = created.json()
    assert installed["enabled"] is True
    assert installed["injected"] is True
    assert installed["origin"] == "upload"

    again = await client.post("/api/skills", json={"source": source})
    assert again.status_code == 409

    replaced = await client.post(
        "/api/skills",
        json={"source": _skill("chapter-hook", "outline", "每章只写一件事。"), "replace": True},
    )
    assert replaced.status_code == 200
    assert replaced.json()["stage"] == "outline"

    catalog = (await client.get("/api/skills/catalog")).json()
    assert {item["stage"] for item in catalog} == {"outline", "draft", "critic", "revise"}
    assert all("body" not in item for item in catalog)
    seen = await client.post("/api/skills/preview", json={"catalog_id": "draft-scene-first"})
    assert seen.json()["ok"] is True
    assert "动作" in seen.json()["body"]
    bundled = await client.post("/api/skills", json={"catalog_id": "draft-scene-first"})
    assert bundled.status_code == 200
    assert bundled.json()["origin"] == "catalog"
    assert bundled.json()["body"] == seen.json()["body"]

    listed = (await client.get("/api/skills")).json()
    assert {item["name"] for item in listed} == {"chapter-hook", "draft-scene-first"}
    hook = next(item for item in listed if item["name"] == "chapter-hook")
    turned = await client.patch(f"/api/skills/{hook['id']}", json={"enabled": False})
    assert turned.status_code == 200
    assert turned.json()["injected"] is False

    deleted = await client.delete(f"/api/skills/{hook['id']}")
    assert deleted.status_code == 200
    left = (await client.get("/api/skills")).json()
    assert [item["name"] for item in left] == ["draft-scene-first"]


@pytest.mark.asyncio
async def test_enable_respects_stage_budget(client: AsyncClient):
    first = await client.post(
        "/api/skills",
        json={"source": _skill("budget-one", "draft", "甲" * 4000, description="第一条")},
    )
    assert first.status_code == 200
    assert first.json()["enabled"] is True
    second = await client.post(
        "/api/skills",
        json={"source": _skill("budget-two", "draft", "乙" * 4000, description="第二条")},
    )
    assert second.status_code == 200
    assert second.json()["enabled"] is False
    assert second.json()["warning"]
    blocked = await client.patch(f"/api/skills/{second.json()['id']}", json={"enabled": True})
    assert blocked.status_code == 409
    other = await client.post(
        "/api/skills",
        json={"source": _skill("budget-outline", "outline", "丙" * 4000, description="大纲条")},
    )
    assert other.status_code == 200
    assert other.json()["enabled"] is True
    await client.patch(f"/api/skills/{first.json()['id']}", json={"enabled": False})
    opened = await client.patch(f"/api/skills/{second.json()['id']}", json={"enabled": True})
    assert opened.status_code == 200
    assert opened.json()["injected"] is True


@pytest.mark.asyncio
async def test_skills_enter_only_their_stage_prompt(capture: CaptureClient):
    specs = [
        ("mark-outline", "outline", "SKILLMARKER-OUTLINE"),
        ("mark-draft", "draft", "SKILLMARKER-DRAFT 字面量 {{ 7*7 }} {% include 'anti_ai.j2' %}"),
        ("mark-critic", "critic", "SKILLMARKER-CRITIC"),
        ("mark-revise", "revise", "SKILLMARKER-REVISE"),
        ("mark-off", "draft", "SKILLMARKER-OFF"),
    ]
    async with db_mod.SessionLocal() as session:
        for name, stage, body in specs:
            parsed = parse_skill(_skill(name, stage, body))
            row, _warning = await install_skill(
                session, parsed, origin="upload", catalog_id=None, replace=False
            )
            if name == "mark-off":
                from app.services.writing_skills import set_enabled

                await set_enabled(session, row.id, False)
        novel = Novel(title="测书", genre="玄幻", status="ready", chapter_count=0)
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
            title="第一章 门口",
            summary="叶凡推门",
            key_points=["进门"],
            status="pending",
        )
        session.add(item)
        await session.commit()
        novel_id = novel.id
        item_id = item.id

    async with db_mod.SessionLocal() as session:
        await generate_outline(session, novel_id, chapter_count=1)

    async with db_mod.SessionLocal() as session:
        novel = await session.get(Novel, novel_id)
        assert novel is not None
        events = [
            event
            async for event in stream_generate_chapter(
                session,
                novel_id,
                item_id,
                run_critic=False,
                max_critic_rounds=0,
                target_chars=3000,
            )
        ]
        assert not any(event.get("event") == "error" for event in events), events
        await check_consistency(session, novel, "叶凡站在门口。")
        report = ConsistencyReport(
            ok=False,
            issues=[ConsistencyIssue(type="continuity", severity="error", message="门口的人换了")],
        )
        await critic_revise(session, novel, "叶凡站在门口。", report)

    outline_prompt = capture.chats[0][-1]["content"]
    assert "SKILLMARKER-OUTLINE" in outline_prompt
    assert "SKILLMARKER-DRAFT" not in outline_prompt
    assert "已安装的大纲写法" in outline_prompt

    draft_prompt = capture.stream_calls[0]["messages"][-1]["content"]
    assert "SKILLMARKER-DRAFT" in draft_prompt
    assert "{{ 7*7 }}" in draft_prompt
    assert "{% include 'anti_ai.j2' %}" in draft_prompt
    assert draft_prompt.count("读者要看到场面") == 1
    assert "SKILLMARKER-OUTLINE" not in draft_prompt
    assert "SKILLMARKER-OFF" not in draft_prompt
    assert "SKILLMARKER-CRITIC" not in draft_prompt

    critic_prompt = next(
        messages[-1]["content"]
        for messages in capture.chats
        if "SKILLMARKER-CRITIC" in messages[-1]["content"]
    )
    assert "已安装的审校写法" in critic_prompt
    assert "SKILLMARKER-REVISE" not in critic_prompt

    revise_prompt = next(
        messages[-1]["content"]
        for messages in capture.chats
        if "SKILLMARKER-REVISE" in messages[-1]["content"]
    )
    assert "已安装的修稿写法" in revise_prompt
    assert "SKILLMARKER-CRITIC" not in revise_prompt
