"""生成章节后的 Story Bible 变更提案。

原稿入库仍直接合并。续写产生的人物、设定、伏笔先落成可勾选提案，确认后才写入。
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.client import get_llm_client
from app.llm.cost_tracker import log_cost
from app.llm.prompts import render
from app.models import BibleProposal, Chapter, Character, Novel, PlotThread, WorldSetting
from app.services.story_bible import _find_character, _norm_name, list_bible
from app.utils.json_extract import extract_json

logger = logging.getLogger(__name__)

PENDING = "pending"
APPLIED = "applied"
DISMISSED = "dismissed"
_STATUSES = {PENDING, APPLIED, DISMISSED}

_FIELD_LABELS = {
    "aliases": "别称",
    "role": "角色",
    "status": "状态",
    "personality": "性格",
    "speech_style": "语言",
    "last_appear_chapter": "最近出场",
    "category": "分类",
    "content": "内容",
    "do_not_violate": "禁止",
    "description": "描述",
    "thread_type": "类型",
    "introduced_chapter": "出现章",
    "resolved_chapter": "回收章",
}
_CHAPTER_KEYS = {"last_appear_chapter", "introduced_chapter", "resolved_chapter"}
_CHAR_PATCH = ("aliases", "role", "status", "personality", "speech_style", "last_appear_chapter")
_WORLD_PATCH = ("category", "content", "do_not_violate")
_THREAD_PATCH = ("description", "thread_type", "status", "introduced_chapter", "resolved_chapter")


class WritebackError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _field(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def _row_id(row: Any) -> int | None:
    value = _field(row, "id")
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number or None


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _alias_list(raw: Any, *, exclude: str = "") -> list[str]:
    items = [raw] if isinstance(raw, str) else list(raw or [])
    skip = _norm_name(exclude)
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = _norm_name(str(item))
        if not text or text == skip or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _display(key: str, value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return "、".join(parts) or None
    if key in _CHAPTER_KEYS:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        if number <= 0:
            return None
        return f"第{number}章"
    text = str(value).strip()
    return text or None


def _push_field(fields: list[dict], patch: dict, key: str, before: Any, after: Any) -> None:
    shown_before = _display(key, before)
    shown_after = _display(key, after)
    if shown_before == shown_after:
        return
    fields.append(
        {
            "key": key,
            "label": _FIELD_LABELS[key],
            "before": shown_before,
            "after": shown_after,
        }
    )
    patch[key] = after


def _names_of(row: Any) -> set[str]:
    names = {_norm_name(str(_field(row, "name") or ""))}
    for alias in _field(row, "aliases") or []:
        names.add(_norm_name(str(alias)))
    names.discard("")
    return names


def _match_character(rows: list, name: str, aliases: list[str]) -> Any | None:
    wanted = {_norm_name(name)} | {_norm_name(alias) for alias in aliases}
    wanted.discard("")
    if not wanted:
        return None
    for row in rows:
        if _names_of(row) & wanted:
            return row
    return None


def _match_title(rows: list, title: str) -> Any | None:
    wanted = _norm_name(title)
    if not wanted:
        return None
    for row in rows:
        if _norm_name(str(_field(row, "title") or "")) == wanted:
            return row
    return None


def _make_change(
    *,
    kind: str,
    op: str,
    label: str,
    summary: str,
    fields: list[dict],
    after: dict,
    target_id: int | None = None,
) -> dict[str, Any]:
    key = _norm_name(label) or label.strip()
    return {
        "id": f"{kind}:{key}",
        "kind": kind,
        "op": op,
        "target_id": target_id,
        "label": label,
        "summary": summary,
        "fields": fields,
        "after": after,
    }


def _character_change(raw: dict, existing: Any | None, *, chapter_index: int | None) -> dict | None:
    name = _norm_name(str(raw.get("name") or ""))
    if not name and existing is not None:
        name = _norm_name(str(_field(existing, "name") or ""))
    if not name:
        return None
    aliases = _alias_list(raw.get("aliases"), exclude=name)
    if existing is None:
        after: dict[str, Any] = {"name": name}
        fields: list[dict] = []
        if aliases:
            after["aliases"] = aliases
            _push_field(fields, {}, "aliases", [], aliases)
        for key in ("role", "status", "personality", "speech_style"):
            text = _text(raw.get(key))
            if not text:
                continue
            after[key] = text
            _push_field(fields, {}, key, None, text)
        if chapter_index is not None:
            after["last_appear_chapter"] = chapter_index
            _push_field(fields, {}, "last_appear_chapter", None, chapter_index)
        return _make_change(
            kind="character",
            op="create",
            label=name,
            summary=f"新增人物「{name}」",
            fields=fields,
            after=after,
        )

    fields = []
    patch: dict[str, Any] = {"name": _norm_name(str(_field(existing, "name") or name))}
    old_aliases = _alias_list(_field(existing, "aliases"))
    merged = list(dict.fromkeys(old_aliases + [alias for alias in aliases if alias not in old_aliases]))
    if set(merged) != set(old_aliases):
        _push_field(fields, patch, "aliases", old_aliases, merged)
    for key in ("role", "status", "personality", "speech_style"):
        incoming = _text(raw.get(key))
        if not incoming:
            continue
        current = _text(_field(existing, key))
        if incoming != current:
            _push_field(fields, patch, key, current or None, incoming)
    if fields and chapter_index is not None and _field(existing, "last_appear_chapter") != chapter_index:
        _push_field(
            fields,
            patch,
            "last_appear_chapter",
            _field(existing, "last_appear_chapter"),
            chapter_index,
        )
    if not fields:
        return None
    label = patch["name"]
    return _make_change(
        kind="character",
        op="update",
        label=label,
        summary=f"更新人物「{label}」",
        fields=fields,
        after=patch,
        target_id=_row_id(existing),
    )


def _world_change(raw: dict, existing: Any | None) -> dict | None:
    content = _text(raw.get("content"))
    title = _norm_name(str(raw.get("title") or ""))
    if not title and content:
        title = _norm_name(content[:20])
    if existing is not None and not title:
        title = _norm_name(str(_field(existing, "title") or ""))
    if not title:
        return None
    if existing is None:
        if not content:
            return None
        after: dict[str, Any] = {
            "title": title,
            "category": _text(raw.get("category")) or "规则",
            "content": content,
        }
        fields: list[dict] = []
        _push_field(fields, {}, "category", None, after["category"])
        _push_field(fields, {}, "content", None, content)
        forbid = _text(raw.get("do_not_violate"))
        if forbid:
            after["do_not_violate"] = forbid
            _push_field(fields, {}, "do_not_violate", None, forbid)
        return _make_change(
            kind="world",
            op="create",
            label=title,
            summary=f"新增设定「{title}」",
            fields=fields,
            after=after,
        )

    fields = []
    patch: dict[str, Any] = {"title": _norm_name(str(_field(existing, "title") or title))}
    if content and content != _text(_field(existing, "content")):
        _push_field(fields, patch, "content", _field(existing, "content"), content)
    category = _text(raw.get("category"))
    if category and category != _text(_field(existing, "category")):
        _push_field(fields, patch, "category", _field(existing, "category"), category)
    forbid = _text(raw.get("do_not_violate"))
    if forbid and forbid != _text(_field(existing, "do_not_violate")):
        _push_field(fields, patch, "do_not_violate", _field(existing, "do_not_violate"), forbid)
    if not fields:
        return None
    label = patch["title"]
    return _make_change(
        kind="world",
        op="update",
        label=label,
        summary=f"更新设定「{label}」",
        fields=fields,
        after=patch,
        target_id=_row_id(existing),
    )


def _thread_change(raw: dict, existing: Any | None, *, chapter_index: int | None) -> dict | None:
    title = _norm_name(str(raw.get("title") or ""))
    if existing is not None and not title:
        title = _norm_name(str(_field(existing, "title") or ""))
    if not title:
        return None
    description = _text(raw.get("description"))
    thread_type = _text(raw.get("thread_type"))
    status = _text(raw.get("status"))
    if existing is None:
        after: dict[str, Any] = {
            "title": title,
            "thread_type": thread_type or "伏笔",
            "status": status or "未回收",
        }
        fields: list[dict] = []
        _push_field(fields, {}, "thread_type", None, after["thread_type"])
        _push_field(fields, {}, "status", None, after["status"])
        if description:
            after["description"] = description
            _push_field(fields, {}, "description", None, description)
        if chapter_index is not None:
            after["introduced_chapter"] = chapter_index
            _push_field(fields, {}, "introduced_chapter", None, chapter_index)
        if after["status"] == "已回收" and chapter_index is not None:
            after["resolved_chapter"] = chapter_index
            _push_field(fields, {}, "resolved_chapter", None, chapter_index)
        summary = f"回收伏笔「{title}」" if after["status"] == "已回收" else f"新增伏笔「{title}」"
        return _make_change(
            kind="thread",
            op="create",
            label=title,
            summary=summary,
            fields=fields,
            after=after,
        )

    fields = []
    patch: dict[str, Any] = {"title": _norm_name(str(_field(existing, "title") or title))}
    if description and description != _text(_field(existing, "description")):
        _push_field(fields, patch, "description", _field(existing, "description"), description)
    if thread_type and thread_type != _text(_field(existing, "thread_type")):
        _push_field(fields, patch, "thread_type", _field(existing, "thread_type"), thread_type)
    if status and status != _text(_field(existing, "status")):
        _push_field(fields, patch, "status", _field(existing, "status"), status)
    if patch.get("status") == "已回收" and _field(existing, "resolved_chapter") is None and chapter_index is not None:
        _push_field(fields, patch, "resolved_chapter", None, chapter_index)
    if patch.get("status") == "未回收" and _field(existing, "resolved_chapter") is not None:
        _push_field(fields, patch, "resolved_chapter", _field(existing, "resolved_chapter"), None)
    if fields and _field(existing, "introduced_chapter") is None and chapter_index is not None:
        _push_field(fields, patch, "introduced_chapter", None, chapter_index)
    if not fields:
        return None
    label = patch["title"]
    summary = f"回收伏笔「{label}」" if patch.get("status") == "已回收" else f"更新伏笔「{label}」"
    return _make_change(
        kind="thread",
        op="update",
        label=label,
        summary=summary,
        fields=fields,
        after=patch,
        target_id=_row_id(existing),
    )


def build_writeback_changes(
    characters: list,
    world_settings: list,
    plot_threads: list,
    extraction: dict[str, Any] | None,
    *,
    chapter_index: int | None,
) -> list[dict[str, Any]]:
    """对照现有 Story Bible，只保留真正有差异的新增或更新。"""
    data = extraction if isinstance(extraction, dict) else {}
    changes: list[dict[str, Any]] = []
    seen: set[str] = set()
    used_characters: set[int] = set()

    def emit(change: dict | None) -> None:
        if change is None or change["id"] in seen:
            return
        seen.add(change["id"])
        changes.append(change)

    for raw in data.get("characters") or []:
        if not isinstance(raw, dict):
            continue
        aliases = _alias_list(raw.get("aliases"), exclude=_text(raw.get("name")))
        existing = _match_character(characters, _text(raw.get("name")), aliases)
        existing_id = _row_id(existing) if existing is not None else None
        if existing_id is not None and existing_id in used_characters:
            continue
        if existing_id is not None:
            used_characters.add(existing_id)
        emit(_character_change(raw, existing, chapter_index=chapter_index))

    for raw in data.get("world_settings") or []:
        if not isinstance(raw, dict):
            continue
        title = _norm_name(str(raw.get("title") or "")) or _norm_name(_text(raw.get("content"))[:20])
        emit(_world_change(raw, _match_title(world_settings, title)))

    for raw in data.get("plot_threads") or []:
        if not isinstance(raw, dict):
            continue
        emit(
            _thread_change(
                raw,
                _match_title(plot_threads, _text(raw.get("title"))),
                chapter_index=chapter_index,
            )
        )
    return changes


async def extract_bible_payload(session: AsyncSession, novel_id: int, chapter: Chapter) -> dict[str, Any]:
    """调用抽取提示词。失败时返回空对象，不抛给入库主流程。"""
    client = get_llm_client()
    prompt = render("extract.j2", title=chapter.title, content=(chapter.content or "")[:8000])
    result = await client.chat(
        [{"role": "user", "content": prompt}],
        endpoint=client.summary_endpoint(),
        temperature=0.2,
        purpose="extract",
    )
    await log_cost(
        session,
        purpose="extract",
        provider=result.provider,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        novel_id=novel_id,
    )
    try:
        data = extract_json(result.text)
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


async def _pending_for_chapter(
    session: AsyncSession, novel_id: int, chapter_id: int
) -> BibleProposal | None:
    return (
        await session.execute(
            select(BibleProposal)
            .where(
                BibleProposal.novel_id == novel_id,
                BibleProposal.chapter_id == chapter_id,
                BibleProposal.status == PENDING,
            )
            .order_by(BibleProposal.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _latest_for_chapter(
    session: AsyncSession, novel_id: int, chapter_id: int
) -> BibleProposal | None:
    return (
        await session.execute(
            select(BibleProposal)
            .where(
                BibleProposal.novel_id == novel_id,
                BibleProposal.chapter_id == chapter_id,
            )
            .order_by(BibleProposal.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _diff_chapter(
    session: AsyncSession, novel_id: int, chapter: Chapter, extraction: dict
) -> list[dict[str, Any]]:
    bible = await list_bible(session, novel_id)
    return build_writeback_changes(
        bible["characters"],
        bible["world_settings"],
        bible["plot_threads"],
        extraction,
        chapter_index=chapter.index,
    )


async def ensure_generated_writeback(
    session: AsyncSession,
    novel: Novel,
    chapter: Chapter,
    *,
    force: bool = False,
) -> BibleProposal:
    """为章节准备一份待确认提案。正文未变且已有同哈希提案时不重复抽取。"""
    digest = content_hash(chapter.content or "")
    pending = await _pending_for_chapter(session, novel.id, chapter.id)
    if pending is not None and pending.content_hash == digest and not force:
        return pending
    if pending is None and not force:
        latest = await _latest_for_chapter(session, novel.id, chapter.id)
        if latest is not None and latest.content_hash == digest:
            return latest

    try:
        extracted = await extract_bible_payload(session, novel.id, chapter)
    except Exception as exc:  # noqa: BLE001
        logger.exception("writeback extract failed novel=%s chapter=%s", novel.id, chapter.id)
        raise WritebackError(502, f"设定抽取失败: {exc}") from exc

    changes = await _diff_chapter(session, novel.id, chapter, extracted)
    row = pending
    if row is None:
        row = BibleProposal(
            novel_id=novel.id,
            chapter_id=chapter.id,
            status=PENDING,
        )
        session.add(row)
    row.chapter_index = chapter.index
    row.status = PENDING
    row.content_hash = digest
    row.changes = changes
    row.applied_ids = []
    await session.flush()
    return row


async def list_proposals(session: AsyncSession, novel_id: int, status: str) -> list[BibleProposal]:
    if status not in _STATUSES:
        raise WritebackError(400, "状态无效")
    rows = (
        await session.execute(
            select(BibleProposal)
            .where(BibleProposal.novel_id == novel_id, BibleProposal.status == status)
            .order_by(BibleProposal.id.desc())
        )
    ).scalars().all()
    return list(rows)


def _assign(row: Any, after: dict, keys: tuple[str, ...]) -> None:
    for key in keys:
        if key not in after:
            continue
        value = after[key]
        if key == "aliases":
            value = list(value or [])
        setattr(row, key, value)


async def _apply_character(session: AsyncSession, novel_id: int, change: dict) -> None:
    after = dict(change.get("after") or {})
    name = _norm_name(str(after.get("name") or change.get("label") or ""))
    aliases = list(after.get("aliases") or [])
    row = None
    target_id = change.get("target_id")
    if target_id:
        found = await session.get(Character, int(target_id))
        if found is not None and found.novel_id == novel_id:
            row = found
    if row is None and name:
        row = await _find_character(session, novel_id, name, aliases)
    if row is None:
        if not name:
            return
        session.add(
            Character(
                novel_id=novel_id,
                name=name,
                aliases=aliases,
                role=after.get("role"),
                status=after.get("status"),
                personality=after.get("personality"),
                speech_style=after.get("speech_style"),
                relationships={},
                last_appear_chapter=after.get("last_appear_chapter"),
            )
        )
        return
    _assign(row, after, _CHAR_PATCH)


async def _find_titled(session: AsyncSession, model: type, novel_id: int, title: str, target_id: Any):
    if target_id:
        found = await session.get(model, int(target_id))
        if found is not None and found.novel_id == novel_id:
            return found
    if not title:
        return None
    return (
        await session.execute(select(model).where(model.novel_id == novel_id, model.title == title))
    ).scalar_one_or_none()


async def _apply_world(session: AsyncSession, novel_id: int, change: dict) -> None:
    after = dict(change.get("after") or {})
    title = _norm_name(str(after.get("title") or change.get("label") or ""))
    row = await _find_titled(session, WorldSetting, novel_id, title, change.get("target_id"))
    if row is None:
        content = _text(after.get("content"))
        if not title or not content:
            return
        session.add(
            WorldSetting(
                novel_id=novel_id,
                category=_text(after.get("category")) or "规则",
                title=title,
                content=content,
                do_not_violate=after.get("do_not_violate"),
            )
        )
        return
    _assign(row, after, _WORLD_PATCH)


async def _apply_thread(session: AsyncSession, novel_id: int, change: dict) -> None:
    after = dict(change.get("after") or {})
    title = _norm_name(str(after.get("title") or change.get("label") or ""))
    row = await _find_titled(session, PlotThread, novel_id, title, change.get("target_id"))
    if row is None:
        if not title:
            return
        session.add(
            PlotThread(
                novel_id=novel_id,
                title=title,
                description=after.get("description"),
                thread_type=_text(after.get("thread_type")) or "伏笔",
                status=_text(after.get("status")) or "未回收",
                introduced_chapter=after.get("introduced_chapter"),
                resolved_chapter=after.get("resolved_chapter"),
            )
        )
        return
    _assign(row, after, _THREAD_PATCH)


async def _apply_one(session: AsyncSession, novel_id: int, change: dict) -> None:
    kind = change.get("kind")
    if kind == "character":
        await _apply_character(session, novel_id, change)
    elif kind == "world":
        await _apply_world(session, novel_id, change)
    elif kind == "thread":
        await _apply_thread(session, novel_id, change)


async def _get_proposal(session: AsyncSession, novel_id: int, proposal_id: int) -> BibleProposal:
    row = await session.get(BibleProposal, proposal_id)
    if row is None or row.novel_id != novel_id:
        raise WritebackError(404, "提案不存在")
    return row


async def apply_proposal(
    session: AsyncSession,
    novel_id: int,
    proposal_id: int,
    change_ids: list[str] | None,
) -> BibleProposal:
    row = await _get_proposal(session, novel_id, proposal_id)
    if row.status != PENDING:
        raise WritebackError(409, "这份提案已经处理过")
    changes = list(row.changes or [])
    if not changes:
        raise WritebackError(400, "没有可写入的变更")
    by_id = {item["id"]: item for item in changes}
    if change_ids is None:
        chosen = changes
    else:
        if not change_ids:
            raise WritebackError(400, "请选择要写入的变更")
        unknown = [item for item in change_ids if item not in by_id]
        if unknown:
            raise WritebackError(400, "包含未知的变更")
        chosen_ids = set(change_ids)
        chosen = [item for item in changes if item["id"] in chosen_ids]
    for change in chosen:
        await _apply_one(session, novel_id, change)
    row.status = APPLIED
    row.applied_ids = [item["id"] for item in chosen]
    await session.flush()
    return row


async def dismiss_proposal(session: AsyncSession, novel_id: int, proposal_id: int) -> BibleProposal:
    row = await _get_proposal(session, novel_id, proposal_id)
    if row.status != PENDING:
        raise WritebackError(409, "这份提案已经处理过")
    row.status = DISMISSED
    await session.flush()
    return row
