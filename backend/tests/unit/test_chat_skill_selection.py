"""System-prompt construction tests for ChatService.

Two concerns:
1. Skill routing — `_select_skill` picks the right skill text based on
   the leading slash command.
2. Active context — `_build_system_prompt` splices a live "Active context"
   block (with the current slug) onto the end of the skill text so the
   agent doesn't have to call `list_projects` to learn which project the
   user is on.
"""
from pathlib import Path
from unittest.mock import AsyncMock

from app.chat.service import ChatService, _UNSET_SLUG, _build_active_context
from app.provider.base import Provider
from app.tools.projects import create_project


def _make_svc(tmp_path: Path) -> ChatService:
    return ChatService(
        workspace=tmp_path,
        provider=AsyncMock(spec=Provider),
        agent_model="claude-sonnet-4-6",
        extract_model="claude-sonnet-4-6",
    )


# ── skill selection ────────────────────────────────────────────────────────


def test_select_skill_publish_loads_publish_skill(tmp_path: Path) -> None:
    svc = _make_svc(tmp_path)
    skill = svc._select_skill("/publish")
    assert "emerge-extractor" in skill
    assert "# emerge-publish" in skill
    assert "---" in skill


def test_select_skill_publish_with_leading_space(tmp_path: Path) -> None:
    svc = _make_svc(tmp_path)
    skill = svc._select_skill(" /publish")
    assert "# emerge-publish" in skill


def test_select_skill_default_does_not_include_publish(tmp_path: Path) -> None:
    svc = _make_svc(tmp_path)
    skill = svc._select_skill("hello")
    assert "# emerge-publish" not in skill
    assert "emerge-extractor" in skill


# ── active context ─────────────────────────────────────────────────────────


async def test_active_context_pins_current_slug(workspace: Path) -> None:
    """When the user is on a project page, the system prompt MUST contain
    the slug verbatim so the agent uses it without calling list_projects."""
    out = await create_project(workspace, name="默沙东_小票")
    slug = out["slug"]
    svc = _make_svc(workspace)
    prompt = svc._build_system_prompt("hi", slug=slug, chat_id="c_aaa111bbb222")
    assert "## Active context" in prompt
    assert slug in prompt
    assert "c_aaa111bbb222" in prompt
    # Don't call list_projects directive is load-bearing.
    assert "Do NOT call `list_projects`" in prompt or "Do NOT call list_projects" in prompt


async def test_active_context_includes_active_prompt_and_model(
    workspace: Path,
) -> None:
    """project.json's active_prompt_id / active_model_id surface in the block
    so the agent doesn't have to read project state to know which prompt
    variant the user is editing."""
    out = await create_project(workspace, name="recipe")
    slug = out["slug"]
    prompt = _build_active_context(workspace, slug, "c_aaa111bbb222")
    assert "pr_baseline" in prompt  # default active prompt set by create_project
    assert "m_default" in prompt    # default active model


def test_active_context_empty_hero(tmp_path: Path) -> None:
    """When slug is the empty-hero sentinel, the block must tell the agent
    there is no project yet so it doesn't blindly call list_projects or
    pass `p_unset` as a real slug."""
    block = _build_active_context(tmp_path, _UNSET_SLUG, "c_aaa111bbb222")
    assert "empty-hero" in block.lower() or "no project yet" in block.lower()
    assert "create_project" in block
    # Must NOT pretend a slug exists.
    assert "`p_unset`" not in block


def test_active_context_handles_missing_project_json(tmp_path: Path) -> None:
    """If project.json is missing (e.g. between mint and atomic flush), the
    block must still render with just the slug — better than crashing."""
    block = _build_active_context(tmp_path, "ghost-slug", "c_aaa111bbb222")
    assert "ghost-slug" in block
    assert "## Active context" in block


async def test_full_system_prompt_has_skill_plus_context(workspace: Path) -> None:
    """End-to-end: `_build_system_prompt` returns skill text AND the active
    context block, separated by the section divider, so the agent reads both."""
    out = await create_project(workspace, name="receipt")
    slug = out["slug"]
    svc = _make_svc(workspace)
    prompt = svc._build_system_prompt(
        "extract these", slug=slug, chat_id="c_aaa111bbb222",
    )
    assert "emerge-extractor" in prompt
    assert "## Active context" in prompt
    # Order: skill first, then active context block at the very end.
    assert prompt.index("emerge-extractor") < prompt.index("## Active context")
