"""`_resolve_proposer_model` resolution chain — proposer model for autoresearch
jobs is per-project (NOT a process-wide singleton bound to env).

Pre-fix bug: `JobRunner` pinned `settings.default_extract_model` at construction
and reused it across every `/improve` call regardless of which project the job
belonged to. This meant a project that switched to `gemini-2.5-pro` would still
see autoresearch propose with the env-default `flash` — a silent correctness
violation of CLAUDE.md's "Proposer = system default + per-job override" rule.

The fix routes resolution through `_resolve_proposer_model`, which honors:
  1. explicit per-call override
  2. `project.json.autoresearch_proposer_model`
  3. `project.json.active_model_id` → `models/{mid}.json`
  4. `settings.default_proposer_model` (env)
  5. `ProposerNotConfiguredError`

These tests pin each link of the chain. They construct project state directly
(no `create_project`) so the test isn't entangled with the bootstrap-seed env
that `create_project` reads."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.jobs.autoresearch import (
    ProposerNotConfiguredError,
    _resolve_proposer_model,
)
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import model_path, models_dir, project_json_path


def _seed_project(
    workspace: Path,
    slug: str,
    *,
    active_model_id: str | None = None,
    autoresearch_proposer_model: str | None = None,
    models: list[dict] | None = None,
) -> None:
    pdir = workspace / slug
    pdir.mkdir(parents=True, exist_ok=True)
    if models:
        models_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
        for m in models:
            atomic_write_json(model_path(workspace, slug, m["model_id"]), m)
    blob = {
        "project_id": "p_test00resolve",
        "slug": slug,
        "name": slug,
        "active_model_id": active_model_id,
        "autoresearch_proposer_model": autoresearch_proposer_model,
    }
    atomic_write_json(project_json_path(workspace, slug), blob)


async def test_resolve_falls_back_to_project_active_model(workspace: Path) -> None:
    """Project active = pro, env empty, no override → proposer = pro."""
    _seed_project(
        workspace,
        "t",
        active_model_id="m_pro",
        models=[{
            "model_id": "m_pro",
            "label": "Pro",
            "provider": "google",
            "provider_model_id": "gemini-2.5-pro",
            "params": {"temperature": 0.0},
            "created_at": "2026-05-27T00:00:00+00:00",
        }],
    )
    _provider, model_id = await _resolve_proposer_model(workspace, "t")
    assert model_id == "gemini-2.5-pro"


async def test_resolve_explicit_override_wins(workspace: Path) -> None:
    """Override (per-call) trumps project active. Override is a project model_id."""
    _seed_project(
        workspace,
        "t",
        active_model_id="m_pro",
        models=[
            {
                "model_id": "m_pro",
                "label": "Pro",
                "provider": "google",
                "provider_model_id": "gemini-2.5-pro",
                "params": {"temperature": 0.0},
                "created_at": "2026-05-27T00:00:00+00:00",
            },
            {
                "model_id": "m_flash",
                "label": "Flash",
                "provider": "google",
                "provider_model_id": "gemini-2.5-flash",
                "params": {"temperature": 0.0},
                "created_at": "2026-05-27T00:00:00+00:00",
            },
        ],
    )
    _provider, model_id = await _resolve_proposer_model(
        workspace, "t", override="m_flash",
    )
    assert model_id == "gemini-2.5-flash"


async def test_resolve_falls_through_to_settings_default(
    workspace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No active_model_id, no autoresearch_proposer_model, env default set
    → proposer = env default."""
    monkeypatch.setenv("EMERGE_DEFAULT_PROPOSER_MODEL", "claude-sonnet-4-6")
    _seed_project(
        workspace,
        "t",
        active_model_id=None,
        autoresearch_proposer_model=None,
    )
    _provider, model_id = await _resolve_proposer_model(workspace, "t")
    assert model_id == "claude-sonnet-4-6"


async def test_resolve_raises_when_unconfigured(workspace: Path) -> None:
    """Nothing set anywhere → raise ProposerNotConfiguredError. The runner is
    the catch site that surfaces this as `autoresearch_failure`."""
    _seed_project(
        workspace,
        "t",
        active_model_id=None,
        autoresearch_proposer_model=None,
    )
    with pytest.raises(ProposerNotConfiguredError):
        await _resolve_proposer_model(workspace, "t")


async def test_resolve_project_proposer_override_wins_over_active(
    workspace: Path,
) -> None:
    """`project.json.autoresearch_proposer_model` is the project-level
    override slot — it should win over `active_model_id` so a user can pin a
    smarter proposer (e.g. always use pro for /improve) while keeping a
    cheaper extract active."""
    _seed_project(
        workspace,
        "t",
        active_model_id="m_flash",
        autoresearch_proposer_model="m_pro",
        models=[
            {
                "model_id": "m_flash",
                "label": "Flash",
                "provider": "google",
                "provider_model_id": "gemini-2.5-flash",
                "params": {"temperature": 0.0},
                "created_at": "2026-05-27T00:00:00+00:00",
            },
            {
                "model_id": "m_pro",
                "label": "Pro",
                "provider": "google",
                "provider_model_id": "gemini-2.5-pro",
                "params": {"temperature": 0.0},
                "created_at": "2026-05-27T00:00:00+00:00",
            },
        ],
    )
    _provider, model_id = await _resolve_proposer_model(workspace, "t")
    assert model_id == "gemini-2.5-pro"
