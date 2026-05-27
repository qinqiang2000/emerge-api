"""Lazy migration drops the legacy `extract_model` / `extract_params` fields
from `project.json` blobs.

Pre-fix: `migrate_project_if_needed` would build `models/m_default.json` from
the legacy `extract_model` value but leave the original blob fields in place,
so the blob carried two copies of the same info — one canonical (`m_default`),
one stale (the legacy field, which would never get updated when the user did
`switch_active_model`). This made `Read project.json` from the agent see a
phantom `extract_model` claim that disagreed with the actual runtime path.

The fix has the migration `pop()` both legacy keys after building the
ModelConfig + setting `active_model_id`, then atomic-writes the cleaned blob.
Idempotent: subsequent migrate calls on an already-cleaned blob no-op.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.workspace.migrate import migrate_project_if_needed
from app.workspace.paths import (
    model_path,
    project_json_path,
)


def _build_legacy_with_extract_model(workspace: Path, pid: str) -> None:
    pdir = workspace / pid
    pdir.mkdir(parents=True, exist_ok=False)
    (pdir / "docs").mkdir()
    (pdir / "predictions" / "_draft").mkdir(parents=True)
    (pdir / "versions").mkdir()
    (pdir / "chats").mkdir()
    # Pre-M9.1 layout: no `models/` dir, no `active_model_id`. The blob
    # carries the legacy `extract_model` field that runtime extract used to
    # consult before the M9.1 migration moved everything to ModelConfig.
    (pdir / "project.json").write_text(json.dumps({
        "name": "legacy",
        "project_type": "extraction",
        "created_at": "2026-05-01T00:00:00+00:00",
        "extract_model": "gemini-2.5-flash",
        "extract_params": {"temperature": 0.0},
        "active_version_id": None,
    }), encoding="utf-8")
    (pdir / "schema.json").write_text(json.dumps([
        {"name": "x", "type": "string", "description": "x", "required": False},
    ]), encoding="utf-8")


async def test_migrate_pops_legacy_extract_model_field(workspace: Path) -> None:
    """After migration, `extract_model` and `extract_params` are gone from
    the blob; `active_model_id` points at the freshly-built `m_default`,
    which itself carries the original `extract_model` value as
    `provider_model_id`. The `models/m_default.json` file exists."""
    pid = "p_legacy00drop"
    _build_legacy_with_extract_model(workspace, pid)

    await migrate_project_if_needed(workspace, pid)

    blob = json.loads(project_json_path(workspace, pid).read_text())
    # (a) legacy fields gone
    assert "extract_model" not in blob
    assert "extract_params" not in blob
    # (b) m_default exists on disk and carries the original env-seeded id
    mc = json.loads(model_path(workspace, pid, "m_default").read_text())
    assert mc["model_id"] == "m_default"
    assert mc["provider_model_id"] == "gemini-2.5-flash"
    # (c) active_model_id repoints at m_default
    assert blob["active_model_id"] == "m_default"


async def test_migrate_idempotent_after_pop(workspace: Path) -> None:
    """Re-migrating an already-cleaned project must not throw and must not
    re-introduce the popped fields. This is what makes lazy migration safe
    to call on every read entry-point — the project blob converges."""
    pid = "p_legacy00idem"
    _build_legacy_with_extract_model(workspace, pid)

    await migrate_project_if_needed(workspace, pid)
    await migrate_project_if_needed(workspace, pid)
    await migrate_project_if_needed(workspace, pid)

    blob = json.loads(project_json_path(workspace, pid).read_text())
    assert "extract_model" not in blob
    assert "extract_params" not in blob
    assert blob["active_model_id"] == "m_default"


async def test_migrate_drops_legacy_fields_on_already_m91_project(workspace: Path) -> None:
    """Critical regression: legacy `create_project` (pre this fix) wrote BOTH
    `active_model_id` and `extract_model` into project.json. Such a project
    is already past M9.1 (prompts/ + models/ exist), so `_migrate_to_m91`
    early-returns and never reaches the field-drop. The drop must therefore
    be a separate idempotent step gated on the keys themselves.

    This is exactly the dogfood scenario: 默沙东_小票 was created May 15 with
    active_model_id=m_default AND extract_model='gemini-2.5-flash'; opening
    the project must drop the legacy keys."""
    pid = "p_postm91"
    pdir = workspace / pid
    pdir.mkdir(parents=True, exist_ok=False)
    (pdir / "docs").mkdir()
    (pdir / "prompts").mkdir()  # M9.1 already done
    (pdir / "models").mkdir()
    # m_default already exists (so _migrate_to_m91 early-returns)
    (pdir / "models" / "m_default.json").write_text(json.dumps({
        "model_id": "m_default",
        "label": "Default",
        "provider": "google",
        "provider_model_id": "gemini-2.5-flash",
        "params": {"temperature": 0.0},
        "created_at": "2026-05-15T00:00:00+00:00",
    }), encoding="utf-8")
    (pdir / "prompts" / "pr_baseline.json").write_text(json.dumps({
        "prompt_id": "pr_baseline",
        "label": "Baseline",
        "schema": [],
        "global_notes": "",
        "derived_from": None,
        "created_at": "2026-05-15T00:00:00+00:00",
        "updated_at": "2026-05-15T00:00:00+00:00",
    }), encoding="utf-8")
    # Blob carries the stale legacy fields the post-M9.1 create_project wrote.
    (pdir / "project.json").write_text(json.dumps({
        "project_id": pid,
        "slug": pid,
        "name": "post-M9.1",
        "project_type": "extraction",
        "created_at": "2026-05-15T00:00:00+00:00",
        "active_prompt_id": "pr_baseline",
        "active_model_id": "m_default",
        "active_version_id": None,
        "autoresearch_proposer_model": None,
        "extract_model": "gemini-2.5-flash",   # <-- stale
        "extract_params": {"temperature": 0.0},  # <-- stale
        "labeler_model": None,
        "published_ids": [],
    }), encoding="utf-8")

    await migrate_project_if_needed(workspace, pid)

    blob = json.loads(project_json_path(workspace, pid).read_text())
    assert "extract_model" not in blob, "post-M9.1 drop step did not run"
    assert "extract_params" not in blob, "post-M9.1 drop step did not run"
    assert blob["active_model_id"] == "m_default"  # untouched
