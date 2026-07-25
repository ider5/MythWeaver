from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class OutlineGenerateIn(BaseModel):
    chapter_count: int = Field(default=5, ge=1, le=50)
    guidance: Optional[str] = None
    start_from_chapter: Optional[int] = None


class OutlineItemIn(BaseModel):
    order: int
    title: str = ""
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    status: str = "pending"


class OutlineItemOut(ORMModel):
    id: int
    outline_id: int
    order: int
    title: str
    summary: str
    key_points: list[str]
    status: str


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
