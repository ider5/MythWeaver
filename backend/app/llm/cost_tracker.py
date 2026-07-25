"""每次 LLM 调用记录 token 与成本。"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import CostLog


PURPOSE_COST_KEYS = {
    "summary": ("cost_summary_input", "cost_summary_output"),
    "extract": ("cost_summary_input", "cost_summary_output"),
    "outline": ("cost_generation_input", "cost_generation_output"),
    "generation": ("cost_generation_input", "cost_generation_output"),
    "critic": ("cost_summary_input", "cost_summary_output"),
    "consistency": ("cost_summary_input", "cost_summary_output"),
    "memory": ("cost_summary_input", "cost_summary_output"),
    "style": ("cost_summary_input", "cost_summary_output"),
    "embed": ("cost_embedding", "cost_embedding"),
}


def estimate_cost(
    purpose: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    settings = get_settings()
    in_key, out_key = PURPOSE_COST_KEYS.get(
        purpose, ("cost_summary_input", "cost_summary_output")
    )
    in_price = getattr(settings, in_key)
    out_price = getattr(settings, out_key)
    return (input_tokens * in_price + output_tokens * out_price) / 1_000_000


async def log_cost(
    session: AsyncSession,
    *,
    purpose: str,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int = 0,
    novel_id: Optional[int] = None,
) -> CostLog:
    cost = estimate_cost(purpose, input_tokens, output_tokens)
    row = CostLog(
        novel_id=novel_id,
        purpose=purpose,
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
    )
    session.add(row)
    await session.flush()
    return row
