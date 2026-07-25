from typing import Any, Optional

from pydantic import BaseModel, Field


class GenerateChapterIn(BaseModel):
    outline_item_id: int
    run_critic: bool = True
    max_critic_rounds: int = Field(default=2, ge=0, le=2)


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
