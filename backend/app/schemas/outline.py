from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel


class OutlineGenerateIn(BaseModel):
    chapter_count: int = Field(default=5, ge=1, le=50)
    guidance: Optional[str] = None
    start_from_chapter: Optional[int] = None


class OutlineGenerateTaskOut(BaseModel):
    """异步生成大纲：立即返回 task_id，通过 SSE 跟踪进度。"""

    task_id: int
    status: str


class OutlineItemIn(BaseModel):
    id: Optional[int] = None
    order: int
    title: str = ""
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    status: str = "pending"
    # 缺省为 None：PUT 未传时保留库内原值，避免旧客户端把蓝图清空。
    purpose: Optional[str] = None
    conflict: Optional[str] = None
    suspense_hook: Optional[str] = None
    characters: Optional[list[str]] = None


class OutlineItemOut(ORMModel):
    id: int
    outline_id: int
    order: int
    title: str
    summary: str
    key_points: list[str]
    purpose: str = ""
    conflict: str = ""
    suspense_hook: str = ""
    characters: list[str] = Field(default_factory=list)
    status: str

    @field_validator("purpose", "conflict", "suspense_hook", mode="before")
    @classmethod
    def _blank_text(cls, value: object) -> object:
        return "" if value is None else value

    @field_validator("key_points", "characters", mode="before")
    @classmethod
    def _blank_list(cls, value: object) -> object:
        return [] if value is None else value


class OutlineOut(ORMModel):
    id: int
    novel_id: int
    title: str
    status: str
    start_from_chapter: int
    created_at: datetime
    updated_at: datetime
    items: list[OutlineItemOut] = Field(default_factory=list)


class OutlineUpdateIn(BaseModel):
    title: Optional[str] = None
    items: Optional[list[OutlineItemIn]] = None


class OutlineDeleteOut(BaseModel):
    message: str
    outline_id: int
    unbound_chapters: int = 0
