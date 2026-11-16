from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel
from app.schemas.story_bible import CharacterOut, PlotThreadOut, WorldSettingOut

NovelRole = Literal["manuscript", "reference"]
NovelOrigin = Literal["import", "scratch"]


class NovelCreate(BaseModel):
    title: str
    author: Optional[str] = None
    genre: str = "玄幻"
    description: Optional[str] = None
    role: NovelRole = "manuscript"


class NovelUpdate(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None
    genre: Optional[str] = None
    description: Optional[str] = None
    role: Optional[NovelRole] = None
    premise: Optional[str] = None
    writing_style: Optional[str] = None


class ScratchCreate(BaseModel):
    """从零开书：前提、题材、文风，不上传原稿。"""

    title: str = Field(..., min_length=1, max_length=256)
    author: Optional[str] = None
    genre: str = Field(default="玄幻", max_length=64)
    premise: str = Field(..., min_length=8, max_length=4000)
    writing_style: str = Field(..., min_length=2, max_length=1000)


class NovelOut(ORMModel):
    id: int
    title: str
    author: Optional[str] = None
    genre: str
    description: Optional[str] = None
    role: NovelRole = "manuscript"
    origin: NovelOrigin = "import"
    premise: Optional[str] = None
    writing_style: Optional[str] = None
    status: str
    total_chars: int
    chapter_count: int
    avg_chapter_chars: int = 0
    median_chapter_chars: int = 0
    created_at: datetime
    updated_at: datetime


class ScratchSeedOut(BaseModel):
    novel: NovelOut
    characters: list[CharacterOut]
    world_settings: list[WorldSettingOut]
    plot_threads: list[PlotThreadOut]


class ChapterPreview(BaseModel):
    index: int
    title: str
    volume: Optional[str] = None
    char_count: int
    preview: str = ""


class ImportPreviewOut(BaseModel):
    title: str
    author: Optional[str] = None
    total_chars: int
    chapter_count: int
    chapters: list[ChapterPreview]
    import_token: str


class ImportConfirmIn(BaseModel):
    import_token: str
    title: Optional[str] = None
    author: Optional[str] = None
    genre: str = "玄幻"
    # manuscript=原稿，进入续写与导出；reference=参考，只拆文风与设定
    role: NovelRole = "manuscript"
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
    outline_item_id: Optional[int] = None
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


class ChapterReviseOut(ORMModel):
    """修订响应：版本已落库；若提交知识库则附带异步 task_id。"""

    id: int
    chapter_id: int
    version_type: str
    content: str
    consistency_report: Optional[dict] = None
    parent_version_id: Optional[int] = None
    created_at: datetime
    task_id: Optional[int] = None


class CriticIssueIn(BaseModel):
    type: str
    severity: str = "warning"
    message: str
    detail: Optional[str] = None


class ParagraphDecisionIn(BaseModel):
    """某一段采用修订，或保留原文。"""

    id: str = Field(..., min_length=1)
    accept: bool = True


class ParagraphHunkOut(BaseModel):
    id: str
    op: str
    before: str = ""
    after: str = ""


class CriticSelectReviseIn(BaseModel):
    """按勾选问题预览修稿：不写版本、不入库。"""

    content: str = Field(..., min_length=1)
    issues: list[CriticIssueIn] = Field(..., min_length=1)
    confirm: bool = Field(
        default=False,
        description="false=仅预览；true=写入 user_edited 版本（仍不自动入库，除非 commit_to_knowledge）",
    )
    commit_to_knowledge: bool = False
    revised_content: Optional[str] = Field(
        default=None,
        description="预览得到的修订稿。按段写入时必填，服务端不再重跑修稿。",
    )
    hunk_decisions: Optional[list[ParagraphDecisionIn]] = Field(
        default=None,
        description="按段采用。省略则整章重跑并写入；给出时 accept=false 的段保留原文。",
    )


class CriticSelectReviseOut(BaseModel):
    base_content: str
    revised_content: str
    consistency: Optional[dict] = None
    changed: bool
    version_id: Optional[int] = None
    task_id: Optional[int] = None
    hunks: list[ParagraphHunkOut] = Field(default_factory=list)


class CommitKnowledgeOut(BaseModel):
    """仅重新入队知识库更新，不新建版本。"""

    chapter_id: int
    task_id: int
    version_id: Optional[int] = None
