"""get_project_config — P4 Task 5 folded get_labeler_config into it.

get_project_config already returned {override, resolved, source} per role —
a superset of get_labeler_config's shape MINUS env_default. Folding the tool
away without adding that field back would turn a surface merge into an
information loss, so this is the one deliberate behavioural increment in the
whole P4 plan (see CLAUDE.md-adjacent plan doc). Covered here for all four
tunable roles: labeler/proposer/translate already computed env_default
internally (their own get_*_config already returned it — verified by
inspection before writing this file); extract had no env-fallback concept at
all, so it gets an explicit `None`.
"""
from __future__ import annotations

from pathlib import Path

import pytest


async def test_project_config_carries_env_default_per_role(
    workspace: Path, monkeypatch,
) -> None:
    """get_labeler_config folded into get_project_config, which returned
    {override, resolved, source} — a superset of the labeler view MINUS
    env_default. Dropping that field would turn a surface merge into an
    information loss, so the merge adds it for all four roles."""
    from app.tools.project_config import get_project_config
    from app.tools.projects import create_project

    monkeypatch.setenv("EMERGE_DEFAULT_LABELER_MODEL", "m_env_labeler")
    slug = (await create_project(workspace, name="p"))["slug"]
    cfg = await get_project_config(workspace, slug)
    for role in ("labeler", "proposer", "translate"):
        assert "env_default" in cfg[role], f"{role} lost env_default"
    assert cfg["labeler"]["env_default"] == "m_env_labeler"


def test_get_labeler_config_is_gone() -> None:
    from app.tools import registered_tool_names

    assert "get_labeler_config" not in registered_tool_names(headless=True)


async def test_project_config_extract_role_env_default_is_none(
    workspace: Path, stub_provider,
) -> None:
    """`extract` is the one role with no env-fallback concept (active_model_id
    is always a project.json override, never an env default) — the brief calls
    this out explicitly so a reader doesn't mistake the missing key for an
    oversight. Only checkable once a model is actually active; unresolved
    `extract` stays `None` wholesale (see get_project_config), so this needs
    its own project setup rather than reusing the bare-project test above."""
    from app.tools.model import create_model, switch_active_model
    from app.tools.project_config import get_project_config
    from app.tools.projects import create_project

    slug = (await create_project(workspace, name="p"))["slug"]
    model_id = await create_model(
        workspace, slug, label="t",
        provider="google", provider_model_id="gemini-2.5-flash",
    )
    await switch_active_model(workspace, slug, model_id)
    cfg = await get_project_config(workspace, slug)
    assert cfg["extract"]["env_default"] is None
