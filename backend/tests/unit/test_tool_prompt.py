from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.schemas.prompt_variant import PromptVariant
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.prompt import (
    PromptClearError,
    PromptNotFoundError,
    list_prompts,
    read_active_prompt,
    read_prompt,
    write_prompt,
)
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    project_json_path,
    prompt_path,
    prompts_dir,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_active_project(workspace: Path, pid: str, schema: list[dict] | None = None) -> None:
    """Build a minimal post-migration project on disk so tests can focus on prompt I/O."""
    pdir = workspace / pid
    pdir.mkdir(parents=True, exist_ok=True)
    prompts_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    atomic_write_json(project_json_path(workspace, pid), {
        "name": "test",
        "active_prompt_id": "pr_baseline",
        "active_model_id": "m_default",
        "active_version_id": None,
    })
    atomic_write_json(prompt_path(workspace, pid, "pr_baseline"), {
        "prompt_id": "pr_baseline",
        "label": "Baseline",
        "schema": schema or [],
        "global_notes": "",
        "derived_from": None,
        "created_at": _now(),
        "updated_at": _now(),
    })


async def test_read_prompt_by_id(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid, schema=[
        {"name": "invoice_no", "type": "string", "description": "d", "required": False}
    ])
    pv = await read_prompt(workspace, pid, "pr_baseline")
    assert pv.prompt_id == "pr_baseline"
    assert len(pv.schema) == 1
    assert pv.schema[0].name == "invoice_no"


async def test_read_prompt_missing_raises(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    with pytest.raises(PromptNotFoundError):
        await read_prompt(workspace, pid, "pr_does_not_exist")


async def test_read_active_prompt_resolves_via_project_json(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid, schema=[
        {"name": "total", "type": "number", "description": "d", "required": False}
    ])
    pv = await read_active_prompt(workspace, pid)
    assert pv.prompt_id == "pr_baseline"
    assert pv.schema[0].name == "total"


async def test_write_prompt_to_active_when_prompt_id_none(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    new_schema = [SchemaField(name="supplier", type=FieldType.STRING, description="supplier name")]
    returned_pid = await write_prompt(
        workspace, pid,
        prompt_id=None,
        schema=new_schema,
        global_notes="some notes",
    )
    assert returned_pid == "pr_baseline"
    # On disk:
    blob = json.loads(prompt_path(workspace, pid, "pr_baseline").read_text())
    assert blob["schema"][0]["name"] == "supplier"
    assert blob["global_notes"] == "some notes"
    assert "updated_at" in blob


async def test_write_prompt_refuses_clearing_non_empty_schema(workspace: Path) -> None:
    """Guard against accidental schema wipes — write_prompt must refuse to
    overwrite a non-empty active prompt with an empty schema unless the
    caller explicitly passes allow_clear=True. Without this guard, an agent
    tool call (or a buggy /init flow on an empty doc set) can silently zero
    out the user's labeled schema, breaking /extract and the right-rail UI."""
    pid = "p_test12345678"
    _seed_active_project(workspace, pid, schema=[
        {"name": "invoice_no", "type": "string", "description": "d", "required": False},
        {"name": "total", "type": "number", "description": "d", "required": False},
    ])

    with pytest.raises(PromptClearError):
        await write_prompt(
            workspace, pid,
            prompt_id=None,
            schema=[],
            global_notes="",
        )

    # Disk is unchanged
    blob = json.loads(prompt_path(workspace, pid, "pr_baseline").read_text())
    assert len(blob["schema"]) == 2


async def test_write_prompt_allows_clearing_with_allow_clear(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid, schema=[
        {"name": "invoice_no", "type": "string", "description": "d", "required": False},
    ])

    await write_prompt(
        workspace, pid,
        prompt_id=None,
        schema=[],
        global_notes="",
        allow_clear=True,
    )

    blob = json.loads(prompt_path(workspace, pid, "pr_baseline").read_text())
    assert blob["schema"] == []


async def test_write_prompt_empty_to_empty_does_not_trigger_guard(workspace: Path) -> None:
    """Writing [] when current schema is already [] is a noop in semantics —
    guard only fires on real clearing of populated schemas."""
    pid = "p_test12345678"
    _seed_active_project(workspace, pid, schema=[])

    await write_prompt(
        workspace, pid,
        prompt_id=None,
        schema=[],
        global_notes="initial notes",
    )

    blob = json.loads(prompt_path(workspace, pid, "pr_baseline").read_text())
    assert blob["schema"] == []
    assert blob["global_notes"] == "initial notes"


async def test_write_prompt_preserves_derived_from_and_created_at(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    # First, manually set a derived_from + created_at on the existing prompt
    pp = prompt_path(workspace, pid, "pr_baseline")
    blob = json.loads(pp.read_text())
    blob["derived_from"] = "pr_parent"
    blob["created_at"] = "2026-01-01T00:00:00+00:00"
    atomic_write_json(pp, blob)

    await write_prompt(
        workspace, pid,
        prompt_id="pr_baseline",
        schema=[SchemaField(name="x", type=FieldType.STRING, description="d")],
        global_notes="",
    )
    after = json.loads(pp.read_text())
    assert after["derived_from"] == "pr_parent"
    assert after["created_at"] == "2026-01-01T00:00:00+00:00"
    # but updated_at changed
    assert after["updated_at"] != "2026-01-01T00:00:00+00:00"


async def test_write_prompt_to_nonexistent_raises(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    with pytest.raises(PromptNotFoundError):
        await write_prompt(
            workspace, pid,
            prompt_id="pr_nope",
            schema=[],
            global_notes="",
        )


async def test_list_prompts_marks_active(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    # add a second prompt manually
    atomic_write_json(prompt_path(workspace, pid, "pr_other"), {
        "prompt_id": "pr_other",
        "label": "Other",
        "schema": [],
        "global_notes": "",
        "derived_from": None,
        "created_at": _now(),
        "updated_at": _now(),
    })
    items = await list_prompts(workspace, pid)
    by_id = {p["prompt_id"]: p for p in items}
    assert by_id["pr_baseline"]["is_active"] is True
    assert by_id["pr_other"]["is_active"] is False
    assert len(items) == 2


async def test_create_prompt_clones_active_when_derived_from_none(workspace: Path) -> None:
    """create_prompt(derived_from=None) clones the current active prompt and mints a new id."""
    from app.tools.prompt import create_prompt
    pid = "p_test12345678"
    _seed_active_project(workspace, pid, schema=[
        {"name": "invoice_no", "type": "string", "description": "d", "required": False}
    ])
    new_id = await create_prompt(workspace, pid, label="trial", derived_from=None)
    assert new_id.startswith("pr_")
    assert new_id != "pr_baseline"

    blob = json.loads(prompt_path(workspace, pid, new_id).read_text())
    assert blob["label"] == "trial"
    assert blob["schema"][0]["name"] == "invoice_no"  # cloned from baseline
    assert blob["derived_from"] == "pr_baseline"


async def test_create_prompt_with_explicit_derived_from(workspace: Path) -> None:
    from app.tools.prompt import create_prompt
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    # add a second prompt to derive from
    atomic_write_json(prompt_path(workspace, pid, "pr_other"), {
        "prompt_id": "pr_other",
        "label": "Other",
        "schema": [{"name": "x", "type": "string", "description": "d", "required": False}],
        "global_notes": "other notes",
        "derived_from": None,
        "created_at": _now(),
        "updated_at": _now(),
    })
    new_id = await create_prompt(workspace, pid, label="trial2", derived_from="pr_other")
    blob = json.loads(prompt_path(workspace, pid, new_id).read_text())
    assert blob["schema"][0]["name"] == "x"
    assert blob["global_notes"] == "other notes"
    assert blob["derived_from"] == "pr_other"


async def test_create_prompt_cross_project_derived_from_string(workspace: Path) -> None:
    """A {src_pid}/{src_prompt_id} string passes through as-is (M9.5 wires actual import)."""
    from app.tools.prompt import create_prompt
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    new_id = await create_prompt(
        workspace, pid,
        label="from us",
        derived_from="p_us_invoice/pr_baseline",  # cross-project literal
    )
    blob = json.loads(prompt_path(workspace, pid, new_id).read_text())
    # NOTE: schema is cloned from active (no cross-project resolution in M9.2);
    # derived_from string is recorded for lineage display only
    assert blob["derived_from"] == "p_us_invoice/pr_baseline"


async def test_switch_active_prompt(workspace: Path) -> None:
    from app.tools.prompt import switch_active_prompt, create_prompt
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    new_id = await create_prompt(workspace, pid, label="v2")
    await switch_active_prompt(workspace, pid, new_id)
    project = json.loads(project_json_path(workspace, pid).read_text())
    assert project["active_prompt_id"] == new_id


async def test_switch_active_prompt_to_nonexistent_raises(workspace: Path) -> None:
    from app.tools.prompt import PromptNotFoundError, switch_active_prompt
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    with pytest.raises(PromptNotFoundError):
        await switch_active_prompt(workspace, pid, "pr_does_not_exist")


async def test_delete_prompt_removes_file(workspace: Path) -> None:
    from app.tools.prompt import create_prompt, delete_prompt
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    new_id = await create_prompt(workspace, pid, label="trial")
    assert prompt_path(workspace, pid, new_id).exists()
    await delete_prompt(workspace, pid, new_id)
    assert not prompt_path(workspace, pid, new_id).exists()


async def test_delete_prompt_blocks_active(workspace: Path) -> None:
    from app.tools.prompt import PromptInUseError, delete_prompt
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    with pytest.raises(PromptInUseError):
        await delete_prompt(workspace, pid, "pr_baseline")


async def test_delete_prompt_missing_raises(workspace: Path) -> None:
    from app.tools.prompt import PromptNotFoundError, delete_prompt
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    with pytest.raises(PromptNotFoundError):
        await delete_prompt(workspace, pid, "pr_nope")


async def test_delete_prompt_blocked_by_non_archived_experiment_reference(
    workspace: Path,
) -> None:
    """A prompt referenced by a non-archived experiment cannot be deleted.
    After archiving the experiment, deletion succeeds. Closes M9.2 follow-up."""
    from app.tools.experiment import archive_experiment, create_experiment
    from app.tools.prompt import (
        PromptInUseError,
        create_prompt,
        delete_prompt,
    )
    pid = "p_test12345678"
    _seed_active_project(workspace, pid, schema=[
        {"name": "x", "type": "string", "description": "d", "required": False}
    ])
    # _seed_active_project sets active_model_id=m_default in project.json but
    # doesn't create the model file; create_experiment validates existence, so
    # seed it explicitly.
    from app.workspace.paths import model_path
    atomic_write_json(model_path(workspace, pid, "m_default"), {
        "model_id": "m_default", "label": "Default",
        "provider": "google", "provider_model_id": "gemini-2.5-flash",
        "params": {}, "created_at": _now(),
    })

    variant_id = await create_prompt(workspace, pid, label="v")
    exp_id = await create_experiment(workspace, pid, prompt_id=variant_id)
    # variant is not active so the M9.2 "is active" check won't fire — but the
    # M9.3 cross-ref check should.
    with pytest.raises(PromptInUseError, match="referenced by experiment"):
        await delete_prompt(workspace, pid, variant_id)

    # after archive, the deletion succeeds
    await archive_experiment(workspace, pid, exp_id)
    await delete_prompt(workspace, pid, variant_id)


# ── content versioning (M-versions) ────────────────────────────────────────


async def test_write_prompt_bumps_version_on_content_change(workspace: Path) -> None:
    """A real content change bumps version and snapshots; the head carries the
    new version + a content_hash."""
    from app.workspace.paths import prompt_version_path

    pid = "p_test12345678"
    _seed_active_project(workspace, pid, schema=[
        {"name": "a", "type": "string", "description": "d", "required": False},
    ])
    new_schema = [SchemaField(name="a", type=FieldType.STRING, description="changed!", required=False)]
    await write_prompt(workspace, pid, prompt_id="pr_baseline", schema=new_schema)

    pv = await read_prompt(workspace, pid, "pr_baseline")
    assert pv.version == 2
    assert pv.content_hash is not None
    # legacy v1 (pre-change) + new v2 are both snapshotted
    assert prompt_version_path(workspace, pid, "pr_baseline", 1).exists()
    assert prompt_version_path(workspace, pid, "pr_baseline", 2).exists()
    v1 = PromptVariant(**json.loads(prompt_version_path(workspace, pid, "pr_baseline", 1).read_text()))
    assert v1.schema[0].description == "d"  # pre-change content preserved


async def test_write_prompt_noop_keeps_version(workspace: Path) -> None:
    """Re-saving identical content does not bump the version."""
    pid = "p_test12345678"
    _seed_active_project(workspace, pid, schema=[
        {"name": "a", "type": "string", "description": "d", "required": False},
    ])
    same = [SchemaField(name="a", type=FieldType.STRING, description="d", required=False)]
    await write_prompt(workspace, pid, prompt_id="pr_baseline", schema=same)
    pv = await read_prompt(workspace, pid, "pr_baseline")
    assert pv.version == 1  # unchanged content → no bump
    assert pv.content_hash is not None  # but legacy blob gets stamped


async def test_write_prompt_label_change_alone_does_not_bump(workspace: Path) -> None:
    """version tracks schema+global_notes, not the cosmetic label. write_prompt
    preserves label, so this asserts the hash ignores it: a notes-only change
    bumps, a re-save of identical content+notes does not."""
    pid = "p_test12345678"
    _seed_active_project(workspace, pid, schema=[
        {"name": "a", "type": "string", "description": "d", "required": False},
    ])
    same = [SchemaField(name="a", type=FieldType.STRING, description="d", required=False)]
    # notes change → bump
    await write_prompt(workspace, pid, prompt_id="pr_baseline", schema=same, global_notes="hello")
    assert (await read_prompt(workspace, pid, "pr_baseline")).version == 2
    # identical re-save → no bump
    await write_prompt(workspace, pid, prompt_id="pr_baseline", schema=same, global_notes="hello")
    assert (await read_prompt(workspace, pid, "pr_baseline")).version == 2


async def test_create_experiment_after_tune_mints_new_experiment(workspace: Path) -> None:
    """Re-running the same (prompt, model) after a tune bumps the prompt version,
    so create_experiment mints a distinct experiment instead of upserting."""
    from app.tools.experiment import create_experiment, read_experiment
    from app.tools.model import read_model  # noqa: F401 — ensure model module import path
    from app.workspace.atomic import atomic_write_json
    from app.workspace.paths import model_path

    pid = "p_test12345678"
    _seed_active_project(workspace, pid, schema=[
        {"name": "a", "type": "string", "description": "d", "required": False},
    ])
    atomic_write_json(model_path(workspace, pid, "m_default"), {
        "model_id": "m_default", "label": "Default", "provider": "google",
        "provider_model_id": "gemini-2.5-flash", "params": {}, "created_at": _now(),
    })

    eid_v1 = await create_experiment(workspace, pid)
    assert (await read_experiment(workspace, pid, eid_v1)).prompt_version == 1

    # tune the prompt → version 2
    await write_prompt(
        workspace, pid, prompt_id="pr_baseline",
        schema=[SchemaField(name="a", type=FieldType.STRING, description="tuned", required=False)],
    )
    eid_v2 = await create_experiment(workspace, pid)
    assert eid_v2 != eid_v1
    ex_v2 = await read_experiment(workspace, pid, eid_v2)
    assert ex_v2.prompt_version == 2
    assert ex_v2.label == "Baseline v2 × gemini-2.5-flash"

    # re-running v2 again is still an upsert (same version) → same id
    assert await create_experiment(workspace, pid) == eid_v2
