"""Bench leaderboard aggregator — pure read over filesystem state.

Plan: docs/superpowers/plans/2026-05-28-bench-leaderboard.md §T2.

`compute_bench(workspace, project_id)` fuses three on-disk signals into the
`BenchResponse` shape consumed by the bench overlay:

1. `experiments/{ex_id}/meta.json` — non-archived experiments (incl. promoted)
2. `metrics/eval_<ts>/{summary,cells,meta}.json` — baseline + experiment evals
3. `reviewed/*.json` — first 6 lex-sorted basenames drive sample column headers

Output shape (per plan §"数据契约"):
    {
        "prompts": [{id, label, is_active, refs}, ...],
        "models":  [{id, label, provider_model_id, is_active, refs}, ...],
        "fields":  [<top-level field names of active prompt>, ...],
        "sample_filenames": [<reviewed basenames>, ...],
        "headline": {best_score, best_prompt_id, best_model_id},
        "rows": [
            {
                "id": "ex_..." | "_baseline",
                "kind": "experiment" | "baseline",
                "prompt_id", "model_id", "status", "is_active",
                "score" | None, "delta" | None,
                "ran_at" | None, "summary_ts" | None,
                "cells": {field_name: {correct, total, strip}}
            },
            ...
        ]
    }

This module is pure compute — no writes, no LLM calls, no chat. Safe to call
from both the HTTP route (T3) and the MCP tool wrapper (T3). Per the
tool-↔-HTTP symmetry invariant, both forms delegate to this exact function.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from app.schemas.experiment import Experiment
from app.workspace.paths import (
    eval_cells_path,
    eval_meta_path,
    eval_summary_path,
    experiments_dir,
    metrics_dir,
    model_path,
    models_dir,
    project_json_path,
    prompt_path,
    prompts_dir,
    reviewed_dir,
)


def _validate_project_id(project_id: str) -> None:
    """Service-layer entry guard — defensive parity with `eval.score`.

    Service is called from both HTTP route (which has stronger `safe_slug`
    validation upstream) and MCP tool (which has weaker untrusted-LLM input).
    Cheap structural check rejects path-traversal / NUL / empty regardless of
    caller, before any filesystem read."""
    if (
        not isinstance(project_id, str)
        or not project_id
        or "/" in project_id
        or "\\" in project_id
        or project_id in (".", "..")
        or "\x00" in project_id
    ):
        raise ValueError("invalid project_id")


def _read_project_json(workspace: Path, project_id: str) -> dict[str, Any]:
    """Read `<project>/project.json`. Missing or malformed → empty dict so
    bench can still render axis metadata in the worst-case empty-project case.
    """
    pj = project_json_path(workspace, project_id)
    if not pj.exists():
        return {}
    try:
        return json.loads(pj.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _read_prompts(workspace: Path, project_id: str) -> list[dict[str, Any]]:
    """Return raw prompt blobs (dict, not PromptVariant) — bench only needs
    `{prompt_id, label, schema}`. Skips malformed/non-json files silently."""
    pd = prompts_dir(workspace, project_id)
    if not pd.exists():
        return []
    out: list[dict[str, Any]] = []
    for child in sorted(pd.iterdir()):
        if not child.is_file() or not child.name.endswith(".json"):
            continue
        try:
            out.append(json.loads(child.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def _read_models(workspace: Path, project_id: str) -> list[dict[str, Any]]:
    """Symmetric to `_read_prompts` for `models/{id}.json`."""
    md = models_dir(workspace, project_id)
    if not md.exists():
        return []
    out: list[dict[str, Any]] = []
    for child in sorted(md.iterdir()):
        if not child.is_file() or not child.name.endswith(".json"):
            continue
        try:
            out.append(json.loads(child.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def _list_experiments(
    workspace: Path, project_id: str,
) -> list[Experiment]:
    """Return non-archived experiments (matching list_experiments default).
    Status=='promoted' is kept (audit trail). Sort newest-first by created_at
    to match list_experiments ordering — keeps row order stable across the
    HTTP listing and the bench rows."""
    edir = experiments_dir(workspace, project_id)
    if not edir.exists():
        return []
    rows: list[Experiment] = []
    for sub in edir.iterdir():
        if not sub.is_dir():
            continue
        meta_path = sub / "meta.json"
        if not meta_path.exists():
            continue
        try:
            ex = Experiment(**json.loads(meta_path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError, Exception):
            # `Experiment` may raise ValidationError; skip the row, don't 500.
            continue
        if ex.status == "archived":
            continue
        rows.append(ex)
    rows.sort(key=lambda e: e.created_at, reverse=True)
    return rows


def _all_experiments_for_refs(
    workspace: Path, project_id: str,
) -> list[Experiment]:
    """Same as `_list_experiments` but for refs-counting context. Plan says
    refs exclude archived (= same as `_list_experiments` output), so we can
    reuse that list. Kept as a separate helper so the intent reads cleanly."""
    return _list_experiments(workspace, project_id)


def _read_eval_meta(workspace: Path, project_id: str, ts: str) -> Optional[dict[str, Any]]:
    p = eval_meta_path(workspace, project_id, ts)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _read_eval_summary(workspace: Path, project_id: str, ts: str) -> Optional[dict[str, Any]]:
    p = eval_summary_path(workspace, project_id, ts)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _read_cells_jsonl(
    workspace: Path, project_id: str, ts: str,
) -> list[dict[str, Any]]:
    """Read cells.jsonl as raw dicts (no CellVerdict instantiation — we only
    read 4 fields). Malformed lines are skipped silently. Missing file → []."""
    p = eval_cells_path(workspace, project_id, ts)
    if not p.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            out.append(json.loads(s))
        except json.JSONDecodeError:
            continue
    return out


def _scan_eval_dirs(workspace: Path, project_id: str) -> list[str]:
    """Return list of `ts` strings for every `metrics/eval_<ts>/` dir present.
    No ordering guarantee — callers sort as needed."""
    md = metrics_dir(workspace, project_id)
    if not md.exists():
        return []
    out: list[str] = []
    for child in md.iterdir():
        if not child.is_dir():
            continue
        name = child.name
        if not name.startswith("eval_"):
            continue
        out.append(name[len("eval_"):])
    return out


def _find_latest_baseline_ts(workspace: Path, project_id: str) -> Optional[str]:
    """Latest `metrics/eval_<ts>/` whose meta.json has `experiment_id is None`.
    'Latest' = lex-max of the ts strings (ts format is ISO-compact so lex is
    chronological)."""
    candidates: list[tuple[str, dict[str, Any]]] = []
    for ts in _scan_eval_dirs(workspace, project_id):
        meta = _read_eval_meta(workspace, project_id, ts)
        if meta is None:
            continue
        if meta.get("experiment_id") is None:
            candidates.append((ts, meta))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][0]


def _find_eval_ts_for_experiment(
    workspace: Path, project_id: str, experiment_id: str,
) -> Optional[str]:
    """Legacy fallback (per plan §"Migration / backward compat"): when
    `experiment.eval.summary_ts is None`, scan `metrics/eval_*/meta.json` for
    `experiment_id == ex_id`; latest by lex-ts wins."""
    candidates: list[str] = []
    for ts in _scan_eval_dirs(workspace, project_id):
        meta = _read_eval_meta(workspace, project_id, ts)
        if meta is None:
            continue
        if meta.get("experiment_id") == experiment_id:
            candidates.append(ts)
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0]


def _active_prompt_fields(prompts: list[dict[str, Any]], active_pid: Optional[str]) -> list[str]:
    """Flatten top-level field names off the active prompt's schema. Per plan:
    'flatten; first do top-level fields, children skipped' — children of
    object/array fields aren't broken out into separate columns."""
    if not active_pid:
        return []
    active = next((p for p in prompts if p.get("prompt_id") == active_pid), None)
    if active is None:
        return []
    schema = active.get("schema") or []
    out: list[str] = []
    for f in schema:
        if isinstance(f, dict):
            name = f.get("name")
            if isinstance(name, str) and name:
                out.append(name)
    return out


def _sample_filenames(workspace: Path, project_id: str, *, n: int = 6) -> list[str]:
    """First `n` lex-sorted basenames under `reviewed/*.json`. Returns the
    basename WITH the `.json` suffix (matches `cells.filename` semantics for
    review/predictions blob keys — `reviewed/inv.pdf.json` has filename
    `inv.pdf` in cells.jsonl, but the column header shows the full reviewed
    file name; the alignment between header and cells is by stripping `.json`
    when joining, see `_compute_strip`)."""
    rd = reviewed_dir(workspace, project_id)
    if not rd.exists():
        return []
    names = sorted(
        p.name for p in rd.iterdir()
        if p.is_file() and p.name.endswith(".json")
    )
    return names[:n]


def _strip_for_cell(
    cells: list[dict[str, Any]],
    filename_no_json: str,
    field: str,
) -> Optional[int]:
    """For one (filename, field), aggregate matching cell verdicts to a
    single tick value:

    - all `correct` / `absent_both` → 1
    - any `wrong` / `missing` / `spurious` → 0
    - no matching verdicts → None (doc not in this row's eval)
    """
    matching = [
        c for c in cells
        if c.get("filename") == filename_no_json and c.get("field") == field
    ]
    if not matching:
        return None
    for c in matching:
        status = c.get("status")
        if status in ("wrong", "missing", "spurious"):
            return 0
    return 1


def _compute_cells(
    cells: list[dict[str, Any]],
    fields: list[str],
    sample_filenames: list[str],
) -> dict[str, dict[str, Any]]:
    """Build the per-row `cells` map:
      {field: {correct, total, strip}}

    * `correct` / `total` aggregate ALL filenames in cells.jsonl (not just the
      6-doc sample) — they're the row's headline N/M numbers.
    * `strip` is the 6-tick aligned-with-sample_filenames array. Each slot is
      1/0/None per `_strip_for_cell`.
    """
    out: dict[str, dict[str, Any]] = {}
    # Index by filename to make per-(filename, field) lookup O(1)
    by_filename: dict[str, list[dict[str, Any]]] = {}
    for c in cells:
        fn = c.get("filename")
        if isinstance(fn, str):
            by_filename.setdefault(fn, []).append(c)

    # All filenames present in this eval (used for the N/M denominator)
    all_filenames = set(by_filename.keys())

    for field in fields:
        correct_count = 0
        total_count = 0
        for fn in all_filenames:
            tick = _strip_for_cell(by_filename[fn], fn, field)
            if tick is None:
                # no verdicts for this (filename, field) — skip; doesn't add
                # to the denominator either.
                continue
            total_count += 1
            if tick == 1:
                correct_count += 1
        # Strip — aligned with sample_filenames; each entry strips `.json`
        # off the reviewed basename to match cells.filename semantics.
        strip: list[Optional[int]] = []
        for sample in sample_filenames:
            fn_no_json = sample[:-len(".json")] if sample.endswith(".json") else sample
            sub_cells = by_filename.get(fn_no_json, [])
            strip.append(_strip_for_cell(sub_cells, fn_no_json, field))
        out[field] = {
            "correct": correct_count,
            "total": total_count,
            "strip": strip,
        }
    return out


def _compute_refs(
    experiments: list[Experiment],
) -> tuple[dict[str, int], dict[str, int]]:
    """Per-axis ref count across the (already filtered) non-archived
    experiment list. Returns (prompt_refs, model_refs) dicts."""
    p_refs: dict[str, int] = {}
    m_refs: dict[str, int] = {}
    for ex in experiments:
        p_refs[ex.prompt_id] = p_refs.get(ex.prompt_id, 0) + 1
        m_refs[ex.model_id] = m_refs.get(ex.model_id, 0) + 1
    return p_refs, m_refs


def _resolve_baseline_axes(
    baseline_meta: Optional[dict[str, Any]],
    project_blob: dict[str, Any],
) -> tuple[Optional[str], Optional[str]]:
    """Per plan: baseline (prompt_id, model_id) comes from `meta.json` (M14
    stamp) with fallback to `project.json.active_*` if meta lacks the field."""
    pid: Optional[str] = None
    mid: Optional[str] = None
    if baseline_meta:
        pid = baseline_meta.get("prompt_id")
        mid = baseline_meta.get("model_id")
    if not pid:
        pid = project_blob.get("active_prompt_id")
    if not mid:
        mid = project_blob.get("active_model_id")
    return pid, mid


def compute_bench(workspace: Path, project_id: str) -> dict[str, Any]:
    """Aggregate the bench leaderboard for one project.

    Pure read; no writes, no LLM calls. See module docstring for shape.
    """
    _validate_project_id(project_id)

    project_blob = _read_project_json(workspace, project_id)
    active_prompt_id = project_blob.get("active_prompt_id")
    active_model_id = project_blob.get("active_model_id")

    prompts_raw = _read_prompts(workspace, project_id)
    models_raw = _read_models(workspace, project_id)
    experiments = _list_experiments(workspace, project_id)
    p_refs, m_refs = _compute_refs(_all_experiments_for_refs(workspace, project_id))

    # Axis metadata
    prompts_out = [
        {
            "id": p.get("prompt_id"),
            "label": p.get("label", ""),
            "is_active": p.get("prompt_id") == active_prompt_id,
            "refs": p_refs.get(p.get("prompt_id", ""), 0),
        }
        for p in prompts_raw
        if isinstance(p.get("prompt_id"), str)
    ]
    models_out = [
        {
            "id": m.get("model_id"),
            "label": m.get("label", ""),
            "provider_model_id": m.get("provider_model_id", ""),
            "is_active": m.get("model_id") == active_model_id,
            "refs": m_refs.get(m.get("model_id", ""), 0),
        }
        for m in models_raw
        if isinstance(m.get("model_id"), str)
    ]

    fields = _active_prompt_fields(prompts_raw, active_prompt_id)
    sample_filenames = _sample_filenames(workspace, project_id)

    # ── Baseline synthetic row ────────────────────────────────────────────
    baseline_ts = _find_latest_baseline_ts(workspace, project_id)
    baseline_score: Optional[float] = None
    baseline_row: Optional[dict[str, Any]] = None
    if baseline_ts is not None:
        baseline_meta = _read_eval_meta(workspace, project_id, baseline_ts)
        baseline_summary = _read_eval_summary(workspace, project_id, baseline_ts)
        b_pid, b_mid = _resolve_baseline_axes(baseline_meta, project_blob)
        score_val = (baseline_summary or {}).get("field_accuracy_macro")
        baseline_score = float(score_val) if isinstance(score_val, (int, float)) else None
        baseline_cells = _read_cells_jsonl(workspace, project_id, baseline_ts)
        baseline_row = {
            "id": "_baseline",
            "kind": "baseline",
            "prompt_id": b_pid,
            "model_id": b_mid,
            "status": "baseline",
            "is_active": True,
            "score": baseline_score,
            "delta": None,
            "ran_at": (baseline_summary or {}).get("ts"),
            "summary_ts": baseline_ts,
            "cells": _compute_cells(baseline_cells, fields, sample_filenames),
        }

    # ── Experiment rows ───────────────────────────────────────────────────
    experiment_rows: list[dict[str, Any]] = []
    for ex in experiments:
        ex_score: Optional[float] = ex.eval.score if ex.eval else None
        # summary_ts — T1 stamp first; fallback to scanning metrics dirs.
        summary_ts: Optional[str] = None
        if ex.eval is not None:
            summary_ts = ex.eval.summary_ts
        if summary_ts is None:
            summary_ts = _find_eval_ts_for_experiment(
                workspace, project_id, ex.experiment_id,
            )

        if summary_ts is not None:
            ex_cells = _read_cells_jsonl(workspace, project_id, summary_ts)
            cells_block = _compute_cells(ex_cells, fields, sample_filenames)
        else:
            cells_block = {}

        delta: Optional[float] = None
        if baseline_score is not None and ex_score is not None:
            delta = ex_score - baseline_score

        experiment_rows.append({
            "id": ex.experiment_id,
            "kind": "experiment",
            "prompt_id": ex.prompt_id,
            "model_id": ex.model_id,
            "status": ex.status,
            "is_active": (
                ex.prompt_id == active_prompt_id
                and ex.model_id == active_model_id
            ),
            "score": ex_score,
            "delta": delta,
            "ran_at": ex.eval.ran_at if ex.eval else None,
            "summary_ts": summary_ts,
            "cells": cells_block,
        })

    rows: list[dict[str, Any]] = []
    if baseline_row is not None:
        rows.append(baseline_row)
    rows.extend(experiment_rows)

    # ── Headline (best row by score) ──────────────────────────────────────
    headline = {"best_score": None, "best_prompt_id": None, "best_model_id": None}
    scored_rows = [r for r in rows if r["score"] is not None]
    if scored_rows:
        best = max(scored_rows, key=lambda r: r["score"])
        headline = {
            "best_score": best["score"],
            "best_prompt_id": best["prompt_id"],
            "best_model_id": best["model_id"],
        }

    return {
        "prompts": prompts_out,
        "models": models_out,
        "fields": fields,
        "sample_filenames": sample_filenames,
        "headline": headline,
        "rows": rows,
    }
