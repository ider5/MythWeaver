from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class CharacterCreate(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    role: Optional[str] = None
    status: Optional[str] = None
    personality: Optional[str] = None
    speech_style: Optional[str] = None
    relationships: dict[str, Any] = Field(default_factory=dict)
    last_appear_chapter: Optional[int] = None
    notes: Optional[str] = None


class CharacterUpdate(CharacterCreate):
    name: Optional[str] = None  # type: ignore[assignment]


class CharacterOut(ORMModel):
    id: int
    novel_id: int
    name: str
    aliases: list[str]
    role: Optional[str] = None
    status: Optional[str] = None
    personality: Optional[str] = None
    speech_style: Optional[str] = None
    relationships: dict[str, Any]
    last_appear_chapter: Optional[int] = None
    notes: Optional[str] = None
    updated_at: datetime


class WorldSettingCreate(BaseModel):
    category: str = "规则"
    title: str = ""
    content: str
    do_not_violate: Optional[str] = None


class WorldSettingUpdate(BaseModel):
    category: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None
    do_not_violate: Optional[str] = None


class WorldSettingOut(ORMModel):
    id: int
    novel_id: int
    category: str
    title: str
    content: str
    do_not_violate: Optional[str] = None
    updated_at: datetime


class PlotThreadCreate(BaseModel):
    title: str
    description: Optional[str] = None
    thread_type: str = "伏笔"
    status: str = "未回收"
    introduced_chapter: Optional[int] = None
    resolved_chapter: Optional[int] = None


class PlotThreadUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    thread_type: Optional[str] = None
    status: Optional[str] = None
    introduced_chapter: Optional[int] = None
    resolved_chapter: Optional[int] = None


class PlotThreadOut(ORMModel):
    id: int
    novel_id: int
    title: str
    description: Optional[str] = None
    thread_type: str
    status: str
    introduced_chapter: Optional[int] = None
    resolved_chapter: Optional[int] = None
    updated_at: datetime


class StoryBibleOut(BaseModel):
    characters: list[CharacterOut]
    world_settings: list[WorldSettingOut]
    plot_threads: list[PlotThreadOut]


class WritebackFieldOut(BaseModel):
    key: str
    label: str
    before: Optional[str] = None
    after: Optional[str] = None


class WritebackChangeOut(BaseModel):
    id: str
    kind: str
    op: str
    target_id: Optional[int] = None
    label: str
    summary: str
    fields: list[WritebackFieldOut] = Field(default_factory=list)
    after: dict[str, Any] = Field(default_factory=dict)


class BibleProposalOut(BaseModel):
    id: int
    novel_id: int
    chapter_id: Optional[int] = None
    chapter_index: Optional[int] = None
    chapter_title: Optional[str] = None
    status: str
    changes: list[WritebackChangeOut]
    created_at: datetime
    updated_at: datetime


class WritebackProposeIn(BaseModel):
    chapter_id: int
    force: bool = False


class WritebackApplyIn(BaseModel):
    """change_ids 省略时写入全部变更。"""

    change_ids: Optional[list[str]] = None
