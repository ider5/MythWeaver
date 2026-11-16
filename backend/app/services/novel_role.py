"""小说角色：原稿可续写并导出；参考只拆文风与设定，不进入正文。"""

from __future__ import annotations

MANUSCRIPT_ROLE = "manuscript"
REFERENCE_ROLE = "reference"
NOVEL_ROLES = (MANUSCRIPT_ROLE, REFERENCE_ROLE)

REFERENCE_EXPORT_DETAIL = "参考小说只用于拆解文风与设定，不能导出为书"
REFERENCE_GENERATION_DETAIL = "参考小说只用于拆解文风与设定，不能作为续写正文来源"


def is_reference_role(role: str | None) -> bool:
    return (role or MANUSCRIPT_ROLE) == REFERENCE_ROLE


def normalize_role(role: str | None) -> str:
    value = (role or MANUSCRIPT_ROLE).strip()
    if value not in NOVEL_ROLES:
        raise ValueError("role 仅支持 manuscript 或 reference")
    return value
