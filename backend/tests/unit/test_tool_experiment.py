import json
from pathlib import Path

import pytest

from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    experiment_meta_path,
    model_path,
    project_json_path,
    prompt_path,
)


def _now() -> str:
    return "2026-05-13T00:00:00+00:00"


def _seed_axes(workspace: Path, pid: str) -> None:
    """Seed a project with one active prompt + one active model."""
    pdir = workspace / pid
    pdir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(project_json_path(workspace, pid), {
        "project_id": pid,
        "name": "Test",
        "created_at": _now(),
        "active_prompt_id": "pr_baseline",
        "active_model_id": "m_default",
    })
    atomic_write_json(prompt_path(workspace, pid, "pr_baseline"), {
        "prompt_id": "pr_baseline",
        "label": "Baseline",
        "schema": [
            {"name": "supplier", "type": "string", "description": "Supplier name", "required": False},
        ],
        "global_notes": "",
        "derived_from": None,
        "created_at": _now(),
        "updated_at": _now(),
    })
    atomic_write_json(model_path(workspace, pid, "m_default"), {
        "model_id": "m_default",
        "label": "Default",
        "provider": "google",
        "provider_model_id": "gemini-2.5-flash",
        "params": {"temperature": 0.0},
        "created_at": _now(),
    })


async def test_create_experiment_defaults_to_active(workspace: Path) -> None:
    from app.tools.experiment import create_experiment, read_experiment
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    eid = await create_experiment(workspace, pid)
    assert eid.startswith("ex_")
    ex = await read_experiment(workspace, pid, eid)
    assert ex.prompt_id == "pr_baseline"
    assert ex.model_id == "m_default"
    assert ex.status == "draft"
    assert ex.eval is None
    assert ex.label.startswith("trial_")


async def test_create_experiment_explicit_axes(workspace: Path) -> None:
    from app.tools.experiment import create_experiment, read_experiment
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    # seed a second prompt and a second model
    atomic_write_json(prompt_path(workspace, pid, "pr_v2"), {
        "prompt_id": "pr_v2", "label": "v2",
        "schema": [{"name": "x", "type": "string", "description": "x", "required": False}],
        "global_notes": "", "derived_from": "pr_baseline",
        "created_at": _now(), "updated_at": _now(),
    })
    atomic_write_json(model_path(workspace, pid, "m_other"), {
        "model_id": "m_other", "label": "Other",
        "provider": "anthropic",
        "provider_model_id": "claude-haiku-4-5-20251001",
        "params": {}, "created_at": _now(),
    })
    eid = await create_experiment(
        workspace, pid, label="custom", prompt_id="pr_v2", model_id="m_other",
    )
    ex = await read_experiment(workspace, pid, eid)
    assert ex.label == "custom"
    assert ex.prompt_id == "pr_v2"
    assert ex.model_id == "m_other"


async def test_create_experiment_missing_prompt_raises(workspace: Path) -> None:
    from app.tools.experiment import create_experiment
    from app.tools.prompt import PromptNotFoundError
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    with pytest.raises(PromptNotFoundError):
        await create_experiment(workspace, pid, prompt_id="pr_missing")


async def test_create_experiment_missing_model_raises(workspace: Path) -> None:
    from app.tools.experiment import create_experiment
    from app.tools.model import ModelNotFoundError
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    with pytest.raises(ModelNotFoundError):
        await create_experiment(workspace, pid, model_id="m_missing")


async def test_list_experiments_excludes_archived_by_default(workspace: Path) -> None:
    from app.tools.experiment import (
        archive_experiment,
        create_experiment,
        list_experiments,
    )
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    e1 = await create_experiment(workspace, pid, label="keep")
    e2 = await create_experiment(workspace, pid, label="hide")
    await archive_experiment(workspace, pid, e2)
    rows_default = await list_experiments(workspace, pid)
    assert [r["experiment_id"] for r in rows_default] == [e1]
    rows_all = await list_experiments(workspace, pid, include_archived=True)
    assert {r["experiment_id"] for r in rows_all} == {e1, e2}


async def test_list_experiments_returns_score_when_available(workspace: Path) -> None:
    from app.tools.experiment import create_experiment, list_experiments
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    eid = await create_experiment(workspace, pid)
    meta = json.loads(experiment_meta_path(workspace, pid, eid).read_text())
    meta["status"] = "ran"
    meta["eval"] = {
        "ran_at": _now(), "score": 0.91,
        "per_field": {"supplier": 1.0}, "per_doc": {},
        "run_id": "r_1", "coverage": 0,
    }
    atomic_write_json(experiment_meta_path(workspace, pid, eid), meta)
    rows = await list_experiments(workspace, pid)
    assert rows[0]["status"] == "ran"
    assert rows[0]["score"] == 0.91
