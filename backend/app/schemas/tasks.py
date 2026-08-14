from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel

from app.schemas.common import ORMModel


class TaskOut(ORMModel):
    id: int
    novel_id: Optional[int] = None
    task_type: str
    status: str
    progress: float
    message: str
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class CostSummaryOut(BaseModel):
    total_cost_usd: float
    total_input_tokens: int
    total_output_tokens: int
    by_purpose: dict[str, float]
    recent: list[dict[str, Any]]


class ConfigOut(BaseModel):
    summary_provider: str
    summary_model: str
    generation_provider: str
    generation_model: str
    embedding_model: str
    context_token_budget: int
    generation_max_tokens: int = 8000
    chapter_segment_threshold: int = 4500
    segment_target_chars: int = 3000
    has_summary_key: bool
    has_generation_key: bool
    has_embedding_key: bool
