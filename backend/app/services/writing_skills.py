"""阶段写法：只解析 SKILL.md 里的提示词。

不执行脚本，不加载 YAML 对象，不读取技能附带的其他文件。
正文按字面量交给对应阶段的 Jinja 模板，不会再被当成模板渲染。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import WritingSkill

logger = logging.getLogger(__name__)

STAGES = ("outline", "draft", "critic", "revise")
STAGE_LABELS = {
    "outline": "大纲",
    "draft": "正文",
    "critic": "审校",
    "revise": "修稿",
}
ALLOWED_KEYS = frozenset({"name", "description", "stage"})
EXECUTABLE_KEYS = frozenset(
    {
        "run",
        "command",
        "commands",
        "script",
        "scripts",
        "shell",
        "tool",
        "tools",
        "allowed-tools",
        "allowed_tools",
        "hooks",
        "hook",
        "entrypoint",
        "entry",
        "executable",
        "bin",
        "args",
        "interpreter",
        "mcp",
        "permissions",
    }
)
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,48}$")
MAX_SOURCE_BYTES = 32_768
MAX_BODY_CHARS = 4_000
MAX_DESCRIPTION_CHARS = 240
MAX_STAGE_CHARS = 8_000
SKILLS_DIR = Path(__file__).resolve().parent.parent / "llm" / "skills"

_UNSAFE = re.compile(
    r"<\s*/?\s*script\b|javascript\s*:|<\s*iframe\b|onerror\s*=|onload\s*=",
    re.IGNORECASE,
)
_BIDI = re.compile("[\u202a-\u202e\u2066-\u2069]")
_SHEBANG = re.compile(r"(?m)^#!")


class SkillParseError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("；".join(errors))


class SkillConflict(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class SkillNotFound(Exception):
    pass


@dataclass(frozen=True)
class ParsedSkill:
    name: str
    description: str
    stage: str
    body: str

    @property
    def stage_label(self) -> str:
        return STAGE_LABELS[self.stage]


def _bad_controls(text: str) -> bool:
    return any(ord(ch) < 32 and ch not in "\n\r\t" for ch in text)


def _find_close(rest: str) -> tuple[int, int] | None:
    """返回 frontmatter 结束标记前的换行位置，以及标记之后的正文起点。"""
    idx = 0
    while True:
        nl = rest.find("\n", idx)
        if nl < 0:
            return None
        line_start = nl + 1
        if line_start >= len(rest):
            return None
        line_end = rest.find("\n", line_start)
        if line_end < 0:
            line = rest[line_start:].strip()
            if line == "---":
                return nl, len(rest)
            return None
        if rest[line_start:line_end].strip() == "---":
            return nl, line_end + 1
        idx = line_start


def _parse_front(front: str, errors: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for raw_line in front.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#") or line[:1] in "-[{":
            errors.append("frontmatter 只接受 name、description、stage 三个单行字段")
            continue
        if ":" not in line:
            errors.append(f"无法识别的字段：{line[:40]}")
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key in EXECUTABLE_KEYS:
            errors.append(f"不执行脚本或工具：发现 {key}")
            continue
        if key not in ALLOWED_KEYS:
            errors.append(f"只接受 name、description、stage，不能包含 {key}")
            continue
        if value[:1] in {"|", ">", "&", "*", "!", "[", "{"}:
            errors.append(f"{key} 只接受单行文字")
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1].strip()
        if key in fields:
            errors.append(f"{key} 重复了")
            continue
        fields[key] = value
    return fields


def parse_skill(source: str) -> ParsedSkill:
    """把一份 SKILL.md 文本解析成提示词。不读文件，不执行任何内容。"""
    if not isinstance(source, str):
        raise SkillParseError(["只接受文本"])
    if "\x00" in source or _bad_controls(source):
        raise SkillParseError(["文件含有控制字符，已拒绝"])
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise SkillParseError([f"文件超过 {MAX_SOURCE_BYTES} 字节，已拒绝"])
    text = source.lstrip("\ufeff")
    if _UNSAFE.search(text) or _BIDI.search(text):
        raise SkillParseError(["提示词里含有脚本或方向控制字符，已拒绝"])
    if not text.startswith("---"):
        raise SkillParseError(["需要以 --- 开头，并写明 name、description、stage"])
    rest = text[3:]
    if rest.startswith("\r\n"):
        rest = rest[2:]
    elif rest.startswith("\n"):
        rest = rest[1:]
    else:
        raise SkillParseError(["frontmatter 的 --- 后面需要换行"])
    close = _find_close(rest)
    if close is None:
        raise SkillParseError(["frontmatter 没有结束的 ---"])
    front, body = rest[: close[0]], rest[close[1] :]
    errors: list[str] = []
    fields = _parse_front(front, errors)
    body = body.strip()
    if _SHEBANG.search(body):
        errors.append("正文以脚本解释器开头，不会执行")
    if not body:
        errors.append("提示词正文是空的")
    elif len(body) > MAX_BODY_CHARS:
        errors.append(f"提示词超过 {MAX_BODY_CHARS} 字，已拒绝")
    name = fields.get("name", "")
    description = fields.get("description", "")
    stage = fields.get("stage", "")
    if "name" not in fields:
        errors.append("缺少 name")
    elif not NAME_RE.fullmatch(name):
        errors.append("name 只能是小写字母、数字和连字符，2–49 字")
    if "description" not in fields:
        errors.append("缺少 description")
    elif not description:
        errors.append("description 不能为空")
    elif len(description) > MAX_DESCRIPTION_CHARS:
        errors.append(f"description 超过 {MAX_DESCRIPTION_CHARS} 字")
    if "stage" not in fields:
        errors.append("缺少 stage")
    elif stage not in STAGES:
        errors.append("stage 只能是 outline、draft、critic、revise")
    if errors:
        raise SkillParseError(errors)
    return ParsedSkill(name=name, description=description, stage=stage, body=body)


def iter_catalog_files() -> list[tuple[str, Path]]:
    """只列出技能目录里、解析后仍在该目录内的 .md。"""
    root = SKILLS_DIR.resolve()
    if not root.is_dir():
        return []
    found: list[tuple[str, Path]] = []
    for path in sorted(root.iterdir()):
        if path.suffix != ".md" or not path.is_file():
            continue
        stem = path.stem
        if not NAME_RE.fullmatch(stem):
            continue
        resolved = path.resolve()
        if resolved.parent != root or not resolved.is_file():
            continue
        found.append((stem, resolved))
    return found


def read_catalog_source(catalog_id: str) -> str:
    if not NAME_RE.fullmatch(catalog_id or ""):
        raise SkillParseError(["未知的示例写法"])
    match = next((path for stem, path in iter_catalog_files() if stem == catalog_id), None)
    if match is None:
        raise SkillParseError(["未知的示例写法"])
    try:
        return match.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise SkillParseError(["示例写法不是 UTF-8 文本"]) from exc


def load_catalog() -> list[tuple[str, ParsedSkill]]:
    items: list[tuple[str, ParsedSkill]] = []
    for catalog_id, _path in iter_catalog_files():
        try:
            parsed = parse_skill(read_catalog_source(catalog_id))
        except SkillParseError as exc:
            logger.warning("跳过无法解析的示例写法 %s：%s", catalog_id, exc)
            continue
        if parsed.name != catalog_id:
            logger.warning("跳过示例写法 %s：name 与文件名不一致", catalog_id)
            continue
        items.append((catalog_id, parsed))
    return items


def format_skill_block(rows: list[tuple[str, str, str]]) -> str:
    parts = [f"[{name}] {description}\n{body.strip()}" for name, description, body in rows]
    return "\n\n".join(parts)


def select_injected(skills: list[WritingSkill]) -> list[WritingSkill]:
    """按 id 顺序纳入，直到本阶段篇幅上限。停用的不进入提示词。"""
    chosen: list[WritingSkill] = []
    for skill in skills:
        if not skill.enabled:
            continue
        trial = chosen + [skill]
        block = format_skill_block([(s.name, s.description, s.body) for s in trial])
        if len(block) <= MAX_STAGE_CHARS:
            chosen.append(skill)
    return chosen


def injected_ids(skills: list[WritingSkill]) -> set[int]:
    by_stage: dict[str, list[WritingSkill]] = {stage: [] for stage in STAGES}
    for skill in skills:
        if skill.stage in by_stage:
            by_stage[skill.stage].append(skill)
    ids: set[int] = set()
    for stage in STAGES:
        for skill in select_injected(by_stage[stage]):
            if skill.id is not None:
                ids.add(skill.id)
    return ids


async def list_skills(session: AsyncSession) -> list[WritingSkill]:
    result = await session.execute(select(WritingSkill).order_by(WritingSkill.id.asc()))
    return list(result.scalars().all())


async def stage_skill_text(session: AsyncSession, stage: str) -> str:
    if stage not in STAGES:
        return ""
    result = await session.execute(
        select(WritingSkill)
        .where(WritingSkill.stage == stage, WritingSkill.enabled.is_(True))
        .order_by(WritingSkill.id.asc())
    )
    chosen = select_injected(list(result.scalars().all()))
    if not chosen:
        return ""
    return format_skill_block([(s.name, s.description, s.body) for s in chosen])


async def _enabled_block(
    session: AsyncSession,
    stage: str,
    extra: tuple[str, str, str] | None,
    exclude_id: int | None,
) -> str:
    result = await session.execute(
        select(WritingSkill)
        .where(WritingSkill.stage == stage, WritingSkill.enabled.is_(True))
        .order_by(WritingSkill.id.asc())
    )
    rows = [s for s in result.scalars().all() if s.id != exclude_id]
    triples = [(s.name, s.description, s.body) for s in rows]
    if extra is not None:
        triples.append(extra)
    return format_skill_block(triples)


async def would_fit(
    session: AsyncSession,
    stage: str,
    name: str,
    description: str,
    body: str,
    *,
    exclude_id: int | None = None,
) -> bool:
    block = await _enabled_block(session, stage, (name, description, body), exclude_id)
    return len(block) <= MAX_STAGE_CHARS


async def find_by_name(session: AsyncSession, name: str) -> WritingSkill | None:
    result = await session.execute(select(WritingSkill).where(WritingSkill.name == name))
    return result.scalar_one_or_none()


async def install_skill(
    session: AsyncSession,
    parsed: ParsedSkill,
    *,
    origin: str,
    catalog_id: str | None,
    replace: bool,
) -> tuple[WritingSkill, str | None]:
    existing = await find_by_name(session, parsed.name)
    if existing is not None and not replace:
        raise SkillConflict("已有同名写法。预览后可以选择覆盖。")
    fit = await would_fit(
        session,
        parsed.stage,
        parsed.name,
        parsed.description,
        parsed.body,
        exclude_id=existing.id if existing is not None else None,
    )
    warning = None
    enabled = True
    if not fit:
        enabled = False
        warning = "这条写法已保存，但本阶段已启用的提示词太长，所以先停用。停掉别的再打开它。"
    if existing is not None:
        existing.description = parsed.description
        existing.stage = parsed.stage
        existing.body = parsed.body
        existing.origin = origin
        existing.catalog_id = catalog_id
        existing.enabled = enabled
        row = existing
    else:
        row = WritingSkill(
            name=parsed.name,
            description=parsed.description,
            stage=parsed.stage,
            body=parsed.body,
            enabled=enabled,
            origin=origin,
            catalog_id=catalog_id,
        )
        session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise SkillConflict("已有同名写法。预览后可以选择覆盖。") from exc
    await session.refresh(row)
    return row, warning


async def set_enabled(session: AsyncSession, skill_id: int, enabled: bool) -> WritingSkill:
    row = await session.get(WritingSkill, skill_id)
    if row is None:
        raise SkillNotFound()
    if enabled and not row.enabled:
        fit = await would_fit(
            session,
            row.stage,
            row.name,
            row.description,
            row.body,
            exclude_id=row.id,
        )
        if not fit:
            raise SkillConflict("本阶段已启用的提示词太长。先停用一条，再打开这条。")
    row.enabled = enabled
    await session.commit()
    await session.refresh(row)
    return row


async def delete_skill(session: AsyncSession, skill_id: int) -> None:
    row = await session.get(WritingSkill, skill_id)
    if row is None:
        raise SkillNotFound()
    await session.delete(row)
    await session.commit()
