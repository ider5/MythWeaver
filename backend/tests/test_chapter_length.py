"""原作均长统计、目标字数夹紧、长章分段规划。"""

from __future__ import annotations

import pytest
import pytest_asyncio

from app.config import get_settings
from app.db import close_db, init_db
from app.llm.prompts import render
from app.models import Chapter, Novel
from app.services.chapter_length import (
    DEFAULT_TARGET_CHARS,
    compute_original_length_stats,
    estimate_generation_max_tokens,
    plan_chapter_segments,
    refresh_original_chapter_stats,
    sample_content_for_critic,
    clamp_target_chars,
)
import app.db as db_mod


def test_compute_stats_uses_median_and_clamps():
    median, avg = compute_original_length_stats([1000, 20000, 21000, 50000])
    # 1000 / 50000 视为异常，统计落在区间内的章
    assert 1500 <= median <= 30000
    assert 1500 <= avg <= 30000
    assert median == 20500
    assert avg == 20500


def test_compute_stats_all_outliers_still_clamped():
    median, avg = compute_original_length_stats([80, 90, 100])
    assert median == 1500
    assert avg == 1500


def test_compute_stats_empty_is_zero():
    median, avg = compute_original_length_stats([])
    assert median == 0
    assert avg == 0


def test_clamp_target_chars():
    assert clamp_target_chars(10) == 1500
    assert clamp_target_chars(40000) == 30000
    assert clamp_target_chars(8000) == 8000


def test_short_target_is_single_segment():
    segs = plan_chapter_segments(3000, ["a", "b", "c"], threshold=4500, segment_target=3000)
    assert len(segs) == 1
    assert segs[0].target_chars == 3000
    assert segs[0].is_last is True
    assert segs[0].key_points == ["a", "b", "c"]


def test_threshold_inclusive_stays_single():
    segs = plan_chapter_segments(4500, ["x"], threshold=4500, segment_target=3000)
    assert len(segs) == 1


def test_long_chapter_segments_by_char_budget():
    segs = plan_chapter_segments(20000, ["遇敌", "破阵"], threshold=4500, segment_target=3000)
    assert len(segs) == 7  # ceil(20000/3000)
    assert sum(s.target_chars for s in segs) == 20000
    assert segs[-1].is_last is True
    assert all(not s.is_last for s in segs[:-1])
    # 要点太少时按字数拆，要点被分到若干段
    assert sum(len(s.key_points) for s in segs) == 2


def test_too_many_key_points_are_grouped():
    points = [f"p{i}" for i in range(15)]
    segs = plan_chapter_segments(9000, points, threshold=4500, segment_target=3000)
    assert len(segs) == 3  # 每段约 3000 字，不因 15 个要点拆成过短段
    assert sorted(p for s in segs for p in s.key_points) == sorted(points)


def test_estimate_max_tokens_scales_with_target():
    short = estimate_generation_max_tokens(2000, min_tokens=1024, max_tokens=8000)
    long_seg = estimate_generation_max_tokens(3500, min_tokens=4000, max_tokens=8000)
    assert short != 6000
    assert 2000 <= short <= 8000
    assert 4000 <= long_seg <= 8000
    assert long_seg >= short


def test_sample_content_for_critic_keeps_head_mid_tail():
    text = "头" * 2000 + "中" * 2000 + "尾" * 2000
    sampled = sample_content_for_critic(text, budget_chars=3000)
    assert len(sampled) < len(text)
    assert sampled.startswith("头")
    assert sampled.endswith("尾")
    assert "中段抽样" in sampled or "……" in sampled


def test_generation_prompt_includes_target_length():
    text = render(
        "generation.j2",
        genre="玄幻",
        genre_hints="",
        story_bible="（空）",
        memory="（空）",
        style_samples="（无）",
        summaries="（无）",
        rag_context="（无）",
        recent_chapters="（无）",
        chapter_title="第四十章",
        chapter_summary="试炼",
        key_points=["遇怪"],
        target_chars=18000,
        is_segment=True,
        segment_index=1,
        segment_total=6,
        segment_target_chars=3000,
        segment_key_points=["遇怪"],
        written_tail="",
        is_last_segment=False,
    )
    assert "本章目标约 18000 字" in text
    assert "±20%" in text
    assert "不得过早收束" in text
    assert "第 1/6 段" in text
    assert "本章完" in text  # 出现在禁止收束的约束里


@pytest_asyncio.fixture
async def db_ready(tmp_path, monkeypatch):
    db_path = tmp_path / "len.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("EMBEDDING_DIMS", "8")
    get_settings.cache_clear()
    db_mod.engine = None
    db_mod.SessionLocal = None
    await init_db()
    yield
    await close_db()
    get_settings.cache_clear()
    db_mod.engine = None
    db_mod.SessionLocal = None


@pytest.mark.asyncio
async def test_refresh_stats_ignores_generated_chapters(db_ready):
    assert db_mod.SessionLocal is not None
    async with db_mod.SessionLocal() as session:
        novel = Novel(title="均长", genre="玄幻", status="ready")
        session.add(novel)
        await session.flush()
        session.add_all(
            [
                Chapter(
                    novel_id=novel.id,
                    index=1,
                    title="一",
                    content="甲" * 8000,
                    char_count=8000,
                    is_generated=False,
                ),
                Chapter(
                    novel_id=novel.id,
                    index=2,
                    title="二",
                    content="乙" * 12000,
                    char_count=12000,
                    is_generated=False,
                ),
                Chapter(
                    novel_id=novel.id,
                    index=3,
                    title="生成章",
                    content="丙" * 2000,
                    char_count=2000,
                    is_generated=True,
                ),
            ]
        )
        await session.commit()
        stats = await refresh_original_chapter_stats(session, novel)
        await session.commit()
        assert stats.median == 10000
        assert stats.avg == 10000
        await session.refresh(novel)
        assert novel.median_chapter_chars == 10000
        assert novel.avg_chapter_chars == 10000


def test_default_target_in_range():
    assert 1500 <= DEFAULT_TARGET_CHARS <= 30000
