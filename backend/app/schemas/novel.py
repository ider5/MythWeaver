from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class NovelCreate(BaseModel):
    title: str
    author: Optional[str] = None
    genre: str = "玄幻"
    description: Optional[str] = None


class NovelUpdate(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None
    genre: Optional[str] = None
    description: Optional[str] = None


class NovelOut(ORMModel):
    id: int
    title: str
    author: Optional[str] = None
    genre: str
    description: Optional[str] = None
    status: str
    total_chars: int
    chapter_count: int
    created_at: datetime
    updated_at: datetime


class ChapterPreview(BaseModel):
    index: int
    title: str
    volume: Optional[str] = None
    char_count: int
    preview: str = ""


class ImportPreviewOut(BaseModel):
    title: str
    total_chars: int
    chapter_count: int
    chapters: list[ChapterPreview]
    import_token: str


class ImportConfirmIn(BaseModel):
    import_token: str
    title: Optional[str] = None
    author: Optional[str] = None
    genre: str = "玄幻"
    # 可选：用户调整后的章节列表（按 preview 结构）
    chapters: Optional[list[ChapterPreview]] = None


class ChapterOut(ORMModel):
    id: int
    novel_id: int
    index: int
    title: str
    volume: Optional[str] = None
    char_count: int
    status: str
    is_generated: bool
    content: Optional[str] = None


class ChapterVersionOut(ORMModel):
    id: int
    chapter_id: int
    version_type: str
    content: str
    consistency_report: Optional[dict] = None
    parent_version_id: Optional[int] = None
    created_at: datetime


class ChapterReviseIn(BaseModel):
    content: str
    commit_to_knowledge: bool = True
