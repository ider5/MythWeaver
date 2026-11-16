from typing import Any, Optional

from pydantic import BaseModel, Field


class GenerateChapterIn(BaseModel):
    outline_item_id: int
    run_critic: bool = True
    max_critic_rounds: int = Field(default=2, ge=0, le=2)
    target_chars: Optional[int] = Field(default=None, ge=500, le=30000)


class BatchGenerateIn(BaseModel):
    """授权一段已确认大纲，按顺序连续生成。"""

    outline_id: int
    from_order: int = Field(ge=1)
    count: int = Field(ge=1, le=10)
    run_critic: bool = True


class BatchGenerateTaskOut(BaseModel):
    task_id: int
    status: str


class ConsistencyIssue(BaseModel):
    type: str
    severity: str = "warning"  # info|warning|error
    message: str
    detail: Optional[str] = None


class ConsistencyReport(BaseModel):
    ok: bool
    issues: list[ConsistencyIssue] = Field(default_factory=list)
    critic_rounds: int = 0
    raw: Optional[dict[str, Any]] = None


class GenerateResultOut(BaseModel):
    chapter_id: int
    version_id: int
    content: str
    consistency: Optional[ConsistencyReport] = None
