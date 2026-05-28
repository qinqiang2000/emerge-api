"""T1 — `ExperimentEval.summary_ts` field + write site in `run_experiment_eval`.

Plan: docs/superpowers/plans/2026-05-28-bench-leaderboard.md §T1.

`summary_ts` audits the per-run `metrics/eval_<ts>/` dir that produced the
score. Bench backend uses it to row-click route to the EvalMatrix modal.
Backwards-compat: pre-T1 `meta.json.eval` blobs have no `summary_ts` key —
they must still deserialize cleanly (Optional, default None).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    experiment_meta_path,
    model_path,
    project_json_path,
    prompt_path,
)


def _now() -> str:
    return "2026-05-28T00:00:00+00:00"


def _seed_axes(workspace: Path, pid: str) -> None:
    """Mirror `tests/unit/test_tool_experiment.py::_seed_axes` — one active
    prompt + one active model, minimal schema."""
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


def _seed_doc(workspace: Path, pid: str, filename: str) -> None:
    """Seed a minimal .png stub + sidecar — mirrors `_seed_doc` in
    `tests/unit/test_tool_experiment.py`."""
    from app.workspace.paths import doc_meta_path, doc_path, docs_dir
    docs_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    doc_path(workspace, pid, filename).write_bytes(
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x08\x00\x00\x00\x08'
        b'\x08\x06\x00\x00\x00\xc4\x0f\xbe\x8b\x00\x00\x00\x0cIDATx\x9cc\xf8'
        b'\xcf\xc0\x00\x00\x00\x03\x00\x01]Z9o\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    meta_p = doc_meta_path(workspace, pid, filename)
    meta_p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(meta_p, {
        "filename": filename, "original_name": filename, "ext": "png",
        "sha256": "stub", "page_count": 1, "uploaded_at": _now(),
    })


async def test_run_experiment_eval_writes_summary_ts(
    workspace: Path, stub_provider,
) -> None:
    """run_experiment_eval must persist the metrics dir ts into
    meta.json.eval.summary_ts (was missing pre-T1 — only in HTTP return).
    The same ts must also appear in the HTTP return blob so client + server
    audit pointers stay in sync."""
    from app.tools.experiment import create_experiment, run_experiment_eval
    from app.workspace.paths import reviewed_dir, reviewed_path
    from tests.conftest import make_provider_result
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    reviewed_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    did = "d_aaaaaaaaaaaa"
    _seed_doc(workspace, pid, did)
    atomic_write_json(reviewed_path(workspace, pid, did), {
        "entities": [{"supplier": "ACME"}], "source": "manual",
    })
    stub_provider.extract.return_value = make_provider_result(
        {"entities": [{"supplier": "ACME"}]},
    )
    eid = await create_experiment(workspace, pid)
    ev = await run_experiment_eval(workspace, pid, eid, provider=stub_provider)

    # HTTP return carries summary_ts (the metrics dir ts).
    assert "summary_ts" in ev
    assert isinstance(ev["summary_ts"], str) and ev["summary_ts"]

    # And the same ts is persisted into meta.json.eval.summary_ts (new field).
    meta = json.loads(experiment_meta_path(workspace, pid, eid).read_text())
    assert meta["eval"]["summary_ts"] == ev["summary_ts"]


def test_legacy_eval_blob_summary_ts_is_none() -> None:
    """Pre-T1 meta.json shapes have no `summary_ts` key — they must still
    deserialize cleanly. Optional default => None."""
    from app.schemas.experiment import Experiment, ExperimentEval
    legacy_eval_blob = {
        "ran_at": _now(),
        "score": 0.91,
        "per_field": {"supplier": 1.0},
        "per_doc": {"d_aaaaaaaaaaaa": 1.0},
        "run_id": "r_1",
        "coverage": 1,
    }
    parsed = ExperimentEval.model_validate(legacy_eval_blob)
    assert parsed.summary_ts is None

    # Same for the full Experiment shape (eval is nested).
    legacy_experiment = {
        "experiment_id": "ex_legacy0000000",
        "label": "Legacy",
        "prompt_id": "pr_baseline",
        "model_id": "m_default",
        "status": "ran",
        "created_at": _now(),
        "promoted_at": None,
        "notes": "",
        "eval": legacy_eval_blob,
    }
    parsed_full = Experiment.model_validate(legacy_experiment)
    assert parsed_full.eval is not None
    assert parsed_full.eval.summary_ts is None


def test_extra_forbid_still_rejects_unknown_key() -> None:
    """Sanity: adding `summary_ts` as a known field must NOT loosen the
    schema. Unknown keys are still rejected by `extra='forbid'`."""
    from app.schemas.experiment import ExperimentEval
    bad_blob = {
        "ran_at": _now(),
        "score": 0.91,
        "per_field": {},
        "per_doc": {},
        "run_id": "r_1",
        "coverage": 0,
        "summary_ts": "20260528T000000",
        "bogus_field": "should not be allowed",
    }
    with pytest.raises(ValidationError):
        ExperimentEval.model_validate(bad_blob)
