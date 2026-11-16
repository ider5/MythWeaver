"""单本小说 ZIP 备份：导出行，并恢复为一本新小说。

不含 WebDAV。任务队列和费用记录不进入备份。章节向量写在
`embedding_json` 里，恢复时按当前维度回填 sqlite-vec。
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import is_vec_available
from app.models import (
    BibleProposal,
    Chapter,
    ChapterVersion,
    Character,
    Novel,
    Outline,
    OutlineItem,
    PlotThread,
    RecurrentMemory,
    StyleSample,
    Summary,
    WorldSetting,
)
from app.services.novel_role import normalize_role
from app.services.scratch import normalize_origin

logger = logging.getLogger(__name__)

FORMAT = "mythweaver-novel-backup"
VERSION = 1
MAX_ZIP_BYTES = 80 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
_TRANSIENT_STATUSES = frozenset({"ingesting", "generating"})
_OMITTED = ("async_tasks", "cost_logs", "chapter_embeddings")
_DT_FIELDS = frozenset({"created_at", "updated_at"})

_TABLE_ORDER = (
    "novels",
    "outlines",
    "outline_items",
    "chapters",
    "chapter_versions",
    "summaries",
    "characters",
    "world_settings",
    "plot_threads",
    "bible_proposals",
    "style_samples",
    "recurrent_memories",
)
_LABELS = {
    "novels": "小说",
    "outlines": "大纲",
    "outline_items": "大纲条目",
    "chapters": "章节",
    "chapter_versions": "章节版本",
    "summaries": "摘要",
    "characters": "人物",
    "world_settings": "世界观",
    "plot_threads": "伏笔",
    "bible_proposals": "设定提案",
    "style_samples": "文风样本",
    "recurrent_memories": "递归记忆",
}
_NOVEL_ID_TABLES = (
    "outlines",
    "chapters",
    "summaries",
    "characters",
    "world_settings",
    "plot_threads",
    "bible_proposals",
    "style_samples",
    "recurrent_memories",
)
_OPTIONAL_FK = {
    "chapters": (("outline_item_id", "outline_items"),),
    "chapter_versions": (("chapter_id", "chapters"),),
    "summaries": (("chapter_id", "chapters"),),
    "bible_proposals": (("chapter_id", "chapters"),),
    "style_samples": (("chapter_id", "chapters"),),
    "outline_items": (("outline_id", "outlines"),),
}
_ROW_FILES = {f"rows/{key}.json": key for key in _TABLE_ORDER}
_ALLOWED_FILES = set(_ROW_FILES) | {"manifest.json"}
_MODELS = {
    "outlines": Outline,
    "outline_items": OutlineItem,
    "chapters": Chapter,
    "chapter_versions": ChapterVersion,
    "summaries": Summary,
    "characters": Character,
    "world_settings": WorldSetting,
    "plot_threads": PlotThread,
    "bible_proposals": BibleProposal,
    "style_samples": StyleSample,
    "recurrent_memories": RecurrentMemory,
}


class BackupError(Exception):
    def __init__(self, detail: str, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class Col:
    name: str
    kind: str
    default: Any = None
    required: bool = False


def _cols(*items: tuple[str, str] | tuple[str, str, Any] | tuple[str, str, Any, bool]) -> tuple[Col, ...]:
    cols: list[Col] = []
    for item in items:
        if len(item) == 2:
            name, kind = item
            cols.append(Col(name, kind, required=True))
        elif len(item) == 3:
            name, kind, default = item
            cols.append(Col(name, kind, default=default, required=False))
        else:
            name, kind, default, required = item
            cols.append(Col(name, kind, default=default, required=required))
    return tuple(cols)


_COLUMNS: dict[str, tuple[Col, ...]] = {
    "novels": _cols(
        ("id", "id"),
        ("title", "str"),
        ("author", "str?", None),
        ("genre", "str", "玄幻"),
        ("role", "str", "manuscript"),
        ("origin", "str", "import"),
        ("description", "str?", None),
        ("premise", "str?", None),
        ("writing_style", "str?", None),
        ("source_path", "str?", None),
        ("status", "str", "imported"),
        ("total_chars", "int", 0),
        ("chapter_count", "int", 0),
        ("avg_chapter_chars", "int", 0),
        ("median_chapter_chars", "int", 0),
        ("created_at", "dt", None),
        ("updated_at", "dt", None),
    ),
    "chapters": _cols(
        ("id", "id"),
        ("novel_id", "int"),
        ("index", "int"),
        ("title", "str", ""),
        ("volume", "str?", None),
        ("content", "str", ""),
        ("char_count", "int", 0),
        ("status", "str", "raw"),
        ("is_generated", "bool", False),
        ("outline_item_id", "int?", None),
        ("embedding_json", "numbers?", None),
        ("created_at", "dt", None),
        ("updated_at", "dt", None),
    ),
    "chapter_versions": _cols(
        ("id", "id"),
        ("chapter_id", "int"),
        ("version_type", "str"),
        ("content", "str"),
        ("consistency_report", "mapping?", None),
        ("parent_version_id", "int?", None),
        ("created_at", "dt", None),
    ),
    "summaries": _cols(
        ("id", "id"),
        ("novel_id", "int"),
        ("chapter_id", "int?", None),
        ("level", "str"),
        ("volume_key", "str?", None),
        ("content", "str"),
        ("created_at", "dt", None),
    ),
    "characters": _cols(
        ("id", "id"),
        ("novel_id", "int"),
        ("name", "str"),
        ("aliases", "strings", []),
        ("role", "str?", None),
        ("status", "str?", None),
        ("personality", "str?", None),
        ("speech_style", "str?", None),
        ("relationships", "mapping", {}),
        ("last_appear_chapter", "int?", None),
        ("notes", "str?", None),
        ("created_at", "dt", None),
        ("updated_at", "dt", None),
    ),
    "world_settings": _cols(
        ("id", "id"),
        ("novel_id", "int"),
        ("category", "str", "规则"),
        ("title", "str", ""),
        ("content", "str"),
        ("do_not_violate", "str?", None),
        ("created_at", "dt", None),
        ("updated_at", "dt", None),
    ),
    "plot_threads": _cols(
        ("id", "id"),
        ("novel_id", "int"),
        ("title", "str"),
        ("description", "str?", None),
        ("thread_type", "str", "伏笔"),
        ("status", "str", "未回收"),
        ("introduced_chapter", "int?", None),
        ("resolved_chapter", "int?", None),
        ("planned_resolve_chapter", "int?", None),
        ("created_at", "dt", None),
        ("updated_at", "dt", None),
    ),
    "bible_proposals": _cols(
        ("id", "id"),
        ("novel_id", "int"),
        ("chapter_id", "int?", None),
        ("chapter_index", "int?", None),
        ("status", "str", "pending"),
        ("content_hash", "str", ""),
        ("changes", "objects", []),
        ("applied_ids", "strings", []),
        ("created_at", "dt", None),
        ("updated_at", "dt", None),
    ),
    "outlines": _cols(
        ("id", "id"),
        ("novel_id", "int"),
        ("title", "str", "续写大纲"),
        ("status", "str", "draft"),
        ("start_from_chapter", "int", 1),
        ("created_at", "dt", None),
        ("updated_at", "dt", None),
    ),
    "outline_items": _cols(
        ("id", "id"),
        ("outline_id", "int"),
        ("order", "int"),
        ("title", "str", ""),
        ("summary", "str", ""),
        ("key_points", "strings", []),
        ("purpose", "str", ""),
        ("conflict", "str", ""),
        ("suspense_hook", "str", ""),
        ("characters", "strings", []),
        ("status", "str", "pending"),
    ),
    "style_samples": _cols(
        ("id", "id"),
        ("novel_id", "int"),
        ("chapter_id", "int?", None),
        ("content", "str"),
        ("reason", "str?", None),
        ("created_at", "dt", None),
    ),
    "recurrent_memories": _cols(
        ("id", "id"),
        ("novel_id", "int"),
        ("last_chapter_index", "int", 0),
        ("ending_state", "str", ""),
        ("character_positions", "mapping", {}),
        ("timeline_cursor", "str?", None),
        ("open_threads", "strings", []),
        ("updated_at", "dt", None),
    ),
}


def backup_filename(title: str) -> str:
    name = (title or "").strip() or "未命名"
    for ch in '\\/:*?"<>|\r\n':
        name = name.replace(ch, "_")
    if len(name) > 80:
        name = name[:80].rstrip() or "未命名"
    return f"{name}.mythweaver.zip"


def _dumps(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


def _dump_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat(timespec="seconds")


def _dump(obj: Any, cols: tuple[Col, ...]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for col in cols:
        value = getattr(obj, col.name)
        if col.kind == "dt":
            value = _dump_dt(value)
        elif col.kind == "bool":
            value = bool(value)
        elif value is None and col.kind == "strings":
            value = []
        elif value is None and col.kind == "mapping":
            value = {}
        elif value is None and col.kind == "objects":
            value = []
        elif value is None and col.kind == "int":
            value = 0 if col.default is None else col.default
        elif value is None and col.kind == "str":
            value = "" if not isinstance(col.default, str) else col.default
        row[col.name] = value
    return row


def _fresh(value: Any) -> Any:
    if isinstance(value, list):
        return []
    if isinstance(value, dict):
        return {}
    return value


def _as_int(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BackupError(f"{where} 必须是整数")
    return value


def _parse_dt(value: Any, where: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise BackupError(f"{where} 的时间格式无效")
    text_value = value.strip()
    if text_value.endswith("Z"):
        text_value = text_value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text_value)
    except ValueError as exc:
        raise BackupError(f"{where} 的时间格式无效") from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _coerce_present(kind: str, value: Any, where: str) -> Any:
    if kind in {"id", "int", "int?"}:
        number = _as_int(value, where)
        if kind == "id" and number < 1:
            raise BackupError(f"{where} 必须是正整数")
        return number
    if kind in {"str", "str?"}:
        if not isinstance(value, str):
            raise BackupError(f"{where} 必须是字符串")
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            raise BackupError(f"{where} 必须是布尔值")
        return value
    if kind == "strings":
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise BackupError(f"{where} 必须是字符串数组")
        return list(value)
    if kind == "objects":
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise BackupError(f"{where} 必须是对象数组")
        return list(value)
    if kind in {"mapping", "mapping?"}:
        if not isinstance(value, dict):
            raise BackupError(f"{where} 必须是对象")
        return dict(value)
    if kind == "numbers?":
        if not isinstance(value, list):
            raise BackupError(f"{where} 必须是数值数组")
        numbers: list[float] = []
        for item in value:
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                raise BackupError(f"{where} 必须是数值数组")
            numbers.append(float(item))
        return numbers
    if kind == "dt":
        return _parse_dt(value, where)
    raise BackupError(f"{where} 无法识别")


def _coerce_row(label: str, raw: Any, cols: tuple[Col, ...]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise BackupError(f"{label} 的每一行必须是对象")
    row: dict[str, Any] = {}
    for col in cols:
        where = f"{label}.{col.name}"
        if col.name not in raw or raw[col.name] is None:
            if col.required:
                raise BackupError(f"{where} 不能为空")
            row[col.name] = _fresh(col.default)
            continue
        row[col.name] = _coerce_present(col.kind, raw[col.name], where)
    return row


def _coerce_table(key: str, raw_rows: Any) -> list[dict[str, Any]]:
    label = _LABELS[key]
    if not isinstance(raw_rows, list):
        raise BackupError(f"{label} 必须是数组")
    rows = [_coerce_row(label, item, _COLUMNS[key]) for item in raw_rows]
    seen: set[int] = set()
    for row in rows:
        if row["id"] in seen:
            raise BackupError(f"{label} 存在重复 id {row['id']}")
        seen.add(row["id"])
    return rows


def _ids(rows: list[dict[str, Any]]) -> set[int]:
    return {row["id"] for row in rows}


def _check_links(tables: dict[str, list[dict[str, Any]]]) -> None:
    novels = tables["novels"]
    if len(novels) != 1:
        if not novels:
            raise BackupError("备份中没有小说")
        raise BackupError("一份备份只能包含一本小说")
    novel_id = novels[0]["id"]
    if not str(novels[0]["title"]).strip():
        raise BackupError("书名不能为空")

    for key in _NOVEL_ID_TABLES:
        label = _LABELS[key]
        for row in tables[key]:
            if row["novel_id"] != novel_id:
                raise BackupError(f"{label} 中有不属于这本小说的行")

    if len(tables["recurrent_memories"]) > 1:
        raise BackupError("递归记忆最多一条")

    id_sets = {key: _ids(rows) for key, rows in tables.items()}
    for key, fields in _OPTIONAL_FK.items():
        label = _LABELS[key]
        for field, target in fields:
            for row in tables[key]:
                value = row[field]
                if value is None:
                    continue
                if value not in id_sets[target]:
                    raise BackupError(f"{label} 引用了不存在的 {field}={value}")

    indexes: set[int] = set()
    for row in tables["chapters"]:
        if row["index"] in indexes:
            raise BackupError(f"章节序号重复: {row['index']}")
        indexes.add(row["index"])

    _check_version_parents(tables["chapter_versions"])


def _check_version_parents(rows: list[dict[str, Any]]) -> None:
    by_id = {row["id"]: row for row in rows}
    for row in rows:
        parent_id = row["parent_version_id"]
        if parent_id is None:
            continue
        parent = by_id.get(parent_id)
        if parent is None:
            raise BackupError(f"章节版本 {row['id']} 的父版本不在备份中")
        if parent["chapter_id"] != row["chapter_id"]:
            raise BackupError("章节版本的父版本必须属于同一章")
        seen: set[int] = set()
        cursor: int | None = row["id"]
        while cursor is not None:
            if cursor in seen:
                raise BackupError("章节版本的父链成环")
            seen.add(cursor)
            current = by_id.get(cursor)
            if current is None:
                raise BackupError(f"章节版本 {row['id']} 的父版本不在备份中")
            cursor = current["parent_version_id"]


def _restored_status(status: str, chapter_count: int) -> str:
    if status in _TRANSIENT_STATUSES:
        return "ready" if chapter_count else "imported"
    return status or "imported"


def _load_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    if info.file_size > MAX_UNCOMPRESSED_BYTES:
        raise BackupError("备份包解压后过大", status_code=413)
    try:
        with zf.open(info, "r") as handle:
            blob = handle.read(MAX_UNCOMPRESSED_BYTES + 1)
    except (RuntimeError, zipfile.BadZipFile) as exc:
        raise BackupError("无法读取备份包") from exc
    if len(blob) > MAX_UNCOMPRESSED_BYTES:
        raise BackupError("备份包解压后过大", status_code=413)
    return blob


def _load_json(blob: bytes, name: str, expect: str) -> Any:
    try:
        data = json.loads(blob.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupError(f"{name} 不是合法 JSON") from exc
    if expect == "list" and not isinstance(data, list):
        raise BackupError(f"{name} 必须是数组")
    if expect == "object" and not isinstance(data, dict):
        raise BackupError(f"{name} 必须是对象")
    return data


def _unpack(raw: bytes) -> dict[str, list[dict[str, Any]]]:
    if len(raw) > MAX_ZIP_BYTES:
        raise BackupError(f"备份包超过 {MAX_ZIP_BYTES // (1024 * 1024)}MB", status_code=413)
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise BackupError("不是有效的 ZIP 备份") from exc

    with zf:
        payloads: dict[str, bytes] = {}
        seen: set[str] = set()
        total = 0
        for info in zf.infolist():
            name = info.filename
            if info.is_dir() or name.endswith("/"):
                if name != "rows/":
                    raise BackupError(f"备份包包含未允许的路径: {name}")
                continue
            if "\\" in name or name.startswith("/") or ".." in name.split("/"):
                raise BackupError(f"备份包包含未允许的路径: {name}")
            if name not in _ALLOWED_FILES:
                raise BackupError(f"备份包包含未允许的文件: {name}")
            if name in seen:
                raise BackupError("备份包包含重复文件")
            seen.add(name)
            blob = _load_member(zf, info)
            total += len(blob)
            if total > MAX_UNCOMPRESSED_BYTES:
                raise BackupError("备份包解压后过大", status_code=413)
            payloads[name] = blob

        if "manifest.json" not in payloads:
            raise BackupError("备份缺少 manifest.json")
        manifest = _load_json(payloads["manifest.json"], "manifest.json", "object")
        if manifest.get("format") != FORMAT:
            raise BackupError("不是 MythWeaver 小说备份")
        if manifest.get("version") != VERSION:
            raise BackupError("不支持的备份版本")

        tables: dict[str, list[dict[str, Any]]] = {}
        for key in _TABLE_ORDER:
            member = f"rows/{key}.json"
            if member not in payloads:
                raw_rows: Any = []
            else:
                raw_rows = _load_json(payloads[member], member, "list")
            tables[key] = _coerce_table(key, raw_rows)

        counts = manifest.get("tables")
        if counts is not None:
            if not isinstance(counts, dict):
                raise BackupError("manifest.tables 必须是对象")
            for key, rows in tables.items():
                if key in counts and counts[key] != len(rows):
                    raise BackupError(f"manifest 中 {key} 的行数与文件不符")

    _check_links(tables)
    return tables


async def _scalars(session: AsyncSession, stmt: Any) -> list[Any]:
    return list((await session.execute(stmt)).scalars().all())


async def _collect(session: AsyncSession, novel: Novel) -> dict[str, list[dict[str, Any]]]:
    novel_id = novel.id
    chapters = await _scalars(
        session,
        select(Chapter).where(Chapter.novel_id == novel_id).order_by(Chapter.index, Chapter.id),
    )
    versions = await _scalars(
        session,
        select(ChapterVersion)
        .join(Chapter, ChapterVersion.chapter_id == Chapter.id)
        .where(Chapter.novel_id == novel_id)
        .order_by(ChapterVersion.id),
    )
    summaries = await _scalars(
        session,
        select(Summary).where(Summary.novel_id == novel_id).order_by(Summary.id),
    )
    characters = await _scalars(
        session,
        select(Character).where(Character.novel_id == novel_id).order_by(Character.id),
    )
    worlds = await _scalars(
        session,
        select(WorldSetting).where(WorldSetting.novel_id == novel_id).order_by(WorldSetting.id),
    )
    threads = await _scalars(
        session,
        select(PlotThread).where(PlotThread.novel_id == novel_id).order_by(PlotThread.id),
    )
    proposals = await _scalars(
        session,
        select(BibleProposal)
        .where(BibleProposal.novel_id == novel_id)
        .order_by(BibleProposal.id),
    )
    outlines = await _scalars(
        session,
        select(Outline).where(Outline.novel_id == novel_id).order_by(Outline.id),
    )
    items = await _scalars(
        session,
        select(OutlineItem)
        .join(Outline, OutlineItem.outline_id == Outline.id)
        .where(Outline.novel_id == novel_id)
        .order_by(OutlineItem.outline_id, OutlineItem.order, OutlineItem.id),
    )
    samples = await _scalars(
        session,
        select(StyleSample).where(StyleSample.novel_id == novel_id).order_by(StyleSample.id),
    )
    memories = await _scalars(
        session,
        select(RecurrentMemory)
        .where(RecurrentMemory.novel_id == novel_id)
        .order_by(RecurrentMemory.id),
    )
    grouped = {
        "novels": [novel],
        "outlines": outlines,
        "outline_items": items,
        "chapters": chapters,
        "chapter_versions": versions,
        "summaries": summaries,
        "characters": characters,
        "world_settings": worlds,
        "plot_threads": threads,
        "bible_proposals": proposals,
        "style_samples": samples,
        "recurrent_memories": memories,
    }
    return {key: [_dump(obj, _COLUMNS[key]) for obj in grouped[key]] for key in _TABLE_ORDER}


def _pack(novel: Novel, tables: dict[str, list[dict[str, Any]]]) -> bytes:
    manifest = {
        "format": FORMAT,
        "version": VERSION,
        "exported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source_novel_id": novel.id,
        "title": novel.title,
        "tables": {key: len(rows) for key, rows in tables.items()},
        "omitted": list(_OMITTED),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", _dumps(manifest))
        for key in _TABLE_ORDER:
            zf.writestr(f"rows/{key}.json", _dumps(tables[key]))
    return buffer.getvalue()


def _kwargs(row: dict[str, Any], replace: dict[str, Any] | None = None) -> dict[str, Any]:
    data = dict(row)
    if replace:
        data.update(replace)
    data.pop("id", None)
    for key in list(data):
        if key in _DT_FIELDS and data[key] is None:
            del data[key]
    return data


async def _add_rows(
    session: AsyncSession,
    model: type,
    rows: list[dict[str, Any]],
    replace_for: Any,
) -> dict[int, int]:
    mapping: dict[int, int] = {}
    pending: list[tuple[int, Any]] = []
    for row in rows:
        obj = model(**_kwargs(row, replace_for(row)))
        session.add(obj)
        pending.append((row["id"], obj))
    await session.flush()
    for old_id, obj in pending:
        mapping[old_id] = obj.id
    return mapping


async def _write_vectors(session: AsyncSession, chapters: list[Chapter]) -> None:
    if not is_vec_available():
        return
    from app.services.retrieval import serialize_vec

    dims = get_settings().embedding_dims
    for chapter in chapters:
        vector = chapter.embedding_json
        if not isinstance(vector, list) or len(vector) != dims:
            continue
        try:
            floats = [float(item) for item in vector]
            await session.execute(
                text("DELETE FROM chapter_embeddings WHERE chapter_id = :cid"),
                {"cid": chapter.id},
            )
            await session.execute(
                text(
                    "INSERT INTO chapter_embeddings(chapter_id, embedding) "
                    "VALUES (:cid, :emb)"
                ),
                {"cid": chapter.id, "emb": serialize_vec(floats)},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("恢复向量失败 chapter_id=%s: %s", chapter.id, exc)


async def _write(session: AsyncSession, tables: dict[str, list[dict[str, Any]]], title: str | None) -> Novel:
    novel_row = dict(tables["novels"][0])
    override = (title or "").strip()
    if override:
        if len(override) > 256:
            raise BackupError("书名不能超过 256 字")
        novel_row["title"] = override
    else:
        novel_row["title"] = str(novel_row["title"]).strip()
    try:
        role = normalize_role(novel_row.get("role"))
        origin = normalize_origin(novel_row.get("origin"))
    except ValueError as exc:
        raise BackupError(str(exc)) from exc

    novel = Novel(
        **_kwargs(
            novel_row,
            {
                "title": novel_row["title"],
                "role": role,
                "origin": origin,
                "status": _restored_status(str(novel_row.get("status") or ""), len(tables["chapters"])),
                "source_path": None,
            },
        )
    )
    session.add(novel)
    await session.flush()
    new_id = novel.id

    def _novel_id(_row: dict[str, Any]) -> dict[str, Any]:
        return {"novel_id": new_id}

    outline_ids = await _add_rows(session, Outline, tables["outlines"], _novel_id)
    item_ids = await _add_rows(
        session,
        OutlineItem,
        tables["outline_items"],
        lambda row: {"outline_id": outline_ids[row["outline_id"]]},
    )

    def _chapter_replace(row: dict[str, Any]) -> dict[str, Any]:
        item_id = row.get("outline_item_id")
        return {
            "novel_id": new_id,
            "outline_item_id": None if item_id is None else item_ids[item_id],
        }

    chapter_ids = await _add_rows(session, Chapter, tables["chapters"], _chapter_replace)
    version_ids = await _add_rows(
        session,
        ChapterVersion,
        tables["chapter_versions"],
        lambda row: {
            "chapter_id": chapter_ids[row["chapter_id"]],
            "parent_version_id": None,
        },
    )
    if version_ids:
        stored = {
            version_ids[row["id"]]: row["parent_version_id"]
            for row in tables["chapter_versions"]
            if row["parent_version_id"] is not None
        }
        if stored:
            versions = await _scalars(
                session, select(ChapterVersion).where(ChapterVersion.id.in_(stored.keys()))
            )
            for version in versions:
                version.parent_version_id = version_ids[stored[version.id]]
            await session.flush()

    def _chapter_fk(row: dict[str, Any]) -> dict[str, Any]:
        chapter_id = row.get("chapter_id")
        return {
            "novel_id": new_id,
            "chapter_id": None if chapter_id is None else chapter_ids[chapter_id],
        }

    await _add_rows(session, Summary, tables["summaries"], _chapter_fk)
    await _add_rows(session, Character, tables["characters"], _novel_id)
    await _add_rows(session, WorldSetting, tables["world_settings"], _novel_id)
    await _add_rows(session, PlotThread, tables["plot_threads"], _novel_id)
    await _add_rows(session, BibleProposal, tables["bible_proposals"], _chapter_fk)
    await _add_rows(session, StyleSample, tables["style_samples"], _chapter_fk)
    await _add_rows(session, RecurrentMemory, tables["recurrent_memories"], _novel_id)

    restored_chapters = await _scalars(
        session, select(Chapter).where(Chapter.novel_id == new_id)
    )
    await _write_vectors(session, restored_chapters)
    return novel


async def export_novel_zip(session: AsyncSession, novel_id: int) -> tuple[bytes, str]:
    novel = await session.get(Novel, novel_id)
    if novel is None:
        raise BackupError("小说不存在", status_code=404)
    tables = await _collect(session, novel)
    return _pack(novel, tables), backup_filename(novel.title)


async def restore_novel_zip(session: AsyncSession, raw: bytes, title: str | None = None) -> Novel:
    tables = _unpack(raw)
    try:
        novel = await _write(session, tables, title)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise BackupError("备份与当前库约束冲突，没有写入新书") from exc
    await session.refresh(novel)
    return novel
