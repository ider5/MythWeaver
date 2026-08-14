"""AI 套话规则层：命中高置信套话，不误伤正常叙事。"""

from app.llm.prompts import render
from app.schemas.generation import ConsistencyIssue, ConsistencyReport
from app.services.consistency import find_ai_voice_cliches, needs_critic_rewrite


def _detail(issues: list[dict]) -> str:
    return issues[0].get("detail") or "" if issues else ""


def test_detect_academic_fillers():
    text = "值得注意的是，秘境入口并不平静。不难发现空气里有血腥味。"
    issues = find_ai_voice_cliches(text)
    assert len(issues) == 1
    assert issues[0]["type"] == "ai_voice"
    assert issues[0]["severity"] == "warning"
    detail = _detail(issues)
    assert "值得注意的是" in detail
    assert "不难发现" in detail


def test_detect_webnovel_cliches():
    text = "叶凡心中一凛。那目光仿佛在说：你逃不掉。一股熟悉的感觉涌上心头。"
    issues = find_ai_voice_cliches(text)
    assert issues
    detail = _detail(issues)
    assert "心中一凛" in detail
    assert "仿佛在说" in detail
    assert "一股熟悉的感觉" in detail


def test_detect_not_only_but_also():
    issues = find_ai_voice_cliches("他不仅看穿了破绽，而且把后路也堵死了。")
    assert issues
    assert "不仅" in _detail(issues)


def test_detect_triple_list():
    text = "首先他拔剑。其次踩碎石阶。最后才抬眼看向城门。"
    issues = find_ai_voice_cliches(text)
    assert issues
    assert "首先" in _detail(issues)


def test_detect_sentence_initial_ciliao():
    issues = find_ai_voice_cliches("叶凡收剑。此外，城墙上还有弓手。")
    assert issues
    assert "此外" in _detail(issues)


def test_detect_repeated_raner_openers():
    text = "然而门没开。然而风停了。然而灯还亮着。"
    issues = find_ai_voice_cliches(text)
    assert issues
    assert "然而" in _detail(issues)


def test_detect_bujin_compound():
    issues = find_ai_voice_cliches("他不禁感到后背发凉，不禁想到昨夜的雨。")
    assert issues
    assert "不禁" in _detail(issues)


def test_clean_action_scene_not_flagged():
    text = (
        "叶凡踏入青阳秘境，玉佩骤然发光。"
        "他想起玉佩发热的那一夜，城门戒严，李四失踪。"
        "「走。」苏婉低声道，声音发紧。"
        "石阶上全是水，靴底打滑。远处有人喊号子。"
    )
    assert find_ai_voice_cliches(text) == []


def test_single_raner_not_flagged():
    assert find_ai_voice_cliches("然而他没有停，直接推门进去。") == []


def test_mid_sentence_ciliao_not_flagged():
    assert find_ai_voice_cliches("除了长剑，此外还有一块碎玉坠在腰间。") == []


def test_single_tongshi_cutaway_not_flagged():
    assert find_ai_voice_cliches("与此同时，城南的鼓响了。") == []


def test_repeated_tongshi_openers():
    text = "与此同时城南鼓响。与此同时北门也亮了灯。"
    issues = find_ai_voice_cliches(text)
    assert issues
    assert "与此同时" in _detail(issues)


def test_not_x_but_y_natural_contrast_not_flagged():
    """仓库禁的是『并非/不仅』模板，不误伤日常『不是……而是』。"""
    assert find_ai_voice_cliches("这不是剑，而是刀。他知道自己只能往前走。") == []


def test_idiom_bujin_not_flagged():
    assert find_ai_voice_cliches("苏婉忍俊不禁，又说这风弱不禁风。") == []


def test_title_line_ignored_like_chapter_meta():
    content = "第四十章：秘境开启\n\n叶凡踏入青阳秘境，玉佩骤然发光。"
    assert find_ai_voice_cliches(content) == []


def test_empty_content():
    assert find_ai_voice_cliches("") == []
    assert find_ai_voice_cliches("   \n  ") == []


def test_needs_critic_rewrite_ai_voice_warning():
    report = ConsistencyReport(
        ok=True,
        issues=[
            ConsistencyIssue(
                type="ai_voice",
                severity="warning",
                message="套话",
            )
        ],
    )
    assert needs_critic_rewrite(report) is True


def test_needs_critic_rewrite_skips_info_only():
    report = ConsistencyReport(
        ok=True,
        issues=[ConsistencyIssue(type="continuity", severity="info", message="提示")],
    )
    assert needs_critic_rewrite(report) is False


def test_generation_prompt_includes_anti_ai_rules():
    text = render(
        "generation.j2",
        genre="玄幻",
        genre_hints="",
        story_bible="（空）",
        memory="（空）",
        style_samples="少年叶凡醒来。",
        summaries="（无）",
        rag_context="（无）",
        recent_chapters="（无）",
        chapter_title="第四十章",
        chapter_summary="试炼",
        key_points=["遇怪"],
        target_chars=3000,
    )
    assert "读者优先" in text
    assert "值得注意的是" in text
    assert "心中一凛" in text
    assert "禁止论文腔" in text
    assert "不要概括或复述样本" in text


def test_critic_prompt_local_fix_not_full_rewrite():
    text = render(
        "critic.j2",
        issues=[{"severity": "warning", "type": "ai_voice", "message": "套话", "detail": "心中一凛"}],
        story_bible="（空）",
        content="叶凡心中一凛。",
    )
    assert "禁止整章重写" in text
    assert "ai_voice" in text
    assert "心中一凛" in text
