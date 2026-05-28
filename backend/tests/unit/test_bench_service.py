"""T2 — Bench aggregator service (pure compute over filesystem state).

Plan: docs/superpowers/plans/2026-05-28-bench-leaderboard.md §T2.

`compute_bench(workspace, project_id) -> dict` is a pure read-aggregator that
fuses three filesystem signals into the bench leaderboard `BenchResponse`:

1. `experiments/{ex_id}/meta.json` (non-archived; includes status==promoted)
2. `metrics/eval_<ts>/{summary,cells,meta}.json` for baseline + experiment evals
3. `reviewed/*.json` (for the 6-doc sample column header set)

Shape contract: see the docstring of `compute_bench` in `app/services/bench.py`
and the plan §"数据契约" — `prompts`, `models`, `fields`, `sample_filenames`,
`headline`, `rows[*]={cells: {field: {correct, total, strip}}}`.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    eval_cells_path,
    eval_dir,
    eval_meta_path,
    eval_summary_path,
    experiment_meta_path,
    model_path,
    project_json_path,
    prompt_path,
    reviewed_dir,
    reviewed_path,
)


def _now() -> str:
    return "2026-05-28T00:00:00+00:00"


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
            {"name": "total", "type": "string", "description": "Total amount", "required": False},
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


def _seed_reviewed(workspace: Path, pid: str, filename: str, entities: list[dict] | None = None) -> None:
    reviewed_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    if entities is None:
        entities = [{"supplier": "ACME", "total": "100"}]
    atomic_write_json(reviewed_path(workspace, pid, filename), {
        "entities": entities,
        "source": "manual",
    })


def _seed_experiment(
    workspace: Path,
    pid: str,
    ex_id: str,
    *,
    prompt_id: str = "pr_baseline",
    model_id: str = "m_default",
    status: str = "draft",
    score: float | None = None,
    summary_ts: str | None = None,
    created_at: str | None = None,
) -> None:
    """Seed `experiments/{ex_id}/meta.json` directly (bypass create_experiment
    so we control the exact (prompt, model, status, eval) tuple)."""
    edir = workspace / pid / "experiments" / ex_id
    edir.mkdir(parents=True, exist_ok=True)
    meta: dict = {
        "experiment_id": ex_id,
        "label": f"{prompt_id} × {model_id}",
        "prompt_id": prompt_id,
        "model_id": model_id,
        "status": status,
        "created_at": created_at or _now(),
        "promoted_at": None,
        "notes": "",
        "eval": None,
    }
    if score is not None:
        meta["eval"] = {
            "ran_at": _now(),
            "score": score,
            "per_field": {},
            "per_doc": {},
            "run_id": "r_test",
            "coverage": 0,
            "summary_ts": summary_ts,
        }
    atomic_write_json(experiment_meta_path(workspace, pid, ex_id), meta)


def _seed_eval_dir(
    workspace: Path,
    pid: str,
    ts: str,
    *,
    experiment_id: str | None,
    field_accuracy_macro: float,
    cells: list[dict],
    prompt_id: str = "pr_baseline",
    model_id: str = "m_default",
) -> None:
    """Write a metrics/eval_<ts>/{summary,cells,meta}.json triple. `cells` is
    the list of CellVerdict dicts (filename, entity_idx, field, status, ...)."""
    d = eval_dir(workspace, pid, ts)
    d.mkdir(parents=True, exist_ok=True)
    summary = {
        "n_docs": 1,
        "n_reviewed": 1,
        "field_accuracy_macro": field_accuracy_macro,
        "macro_f1": None,
        "doc_accuracy": field_accuracy_macro,
        "doc_accuracy_strict": field_accuracy_macro,
        "per_field": [],
        "errors": [],
        "ts": ts,
        "schema_field_count": 0,
        "judge_used": 0,
        "judge_skipped_budget": 0,
        "prompt_id": prompt_id,
        "prompt_label": "Baseline",
        "model_id": model_id,
        "extract_model": "gemini-2.5-flash",
    }
    atomic_write_json(eval_summary_path(workspace, pid, ts), summary)
    meta = {
        "prompt_id": prompt_id,
        "prompt_label": "Baseline",
        "model_id": model_id,
        "extract_model": "gemini-2.5-flash",
        "experiment_id": experiment_id,
        "judge_used": 0,
        "judge_skipped_budget": 0,
        "ts": ts,
        "schema_field_count": 0,
        "n_reviewed": 1,
    }
    atomic_write_json(eval_meta_path(workspace, pid, ts), meta)
    # write cells.jsonl
    cells_path = eval_cells_path(workspace, pid, ts)
    if cells:
        cells_path.write_text(
            "\n".join(json.dumps(c, ensure_ascii=False) for c in cells) + "\n",
            encoding="utf-8",
        )
    else:
        cells_path.write_text("", encoding="utf-8")


def _cell(filename: str, field: str, status: str, *, entity_idx: int = 0) -> dict:
    """Minimal CellVerdict-shaped dict; only fields read by compute_bench."""
    base: dict = {
        "filename": filename,
        "entity_idx": entity_idx,
        "field": field,
        "status": status,
        "verdict_source": "exact",
    }
    if status in ("correct", "wrong"):
        base["truth"] = "x"
        base["pred"] = "x" if status == "correct" else "y"
    elif status == "missing":
        base["truth"] = "x"
    elif status == "spurious":
        base["pred"] = "y"
    return base


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_empty_project(workspace: Path) -> None:
    """No experiments, no metrics → rows=[]; headline all-None."""
    from app.services.bench import compute_bench
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    out = compute_bench(workspace, pid)
    assert out["rows"] == []
    assert out["headline"]["best_score"] is None
    assert out["headline"]["best_prompt_id"] is None
    assert out["headline"]["best_model_id"] is None
    # axes still present (just the seeded baseline + default model)
    assert any(p["id"] == "pr_baseline" and p["is_active"] for p in out["prompts"])
    assert any(m["id"] == "m_default" and m["is_active"] for m in out["models"])
    # No reviewed docs → empty sample column header set
    assert out["sample_filenames"] == []


async def test_baseline_only(workspace: Path) -> None:
    """One baseline eval (no experiment) → 1 row kind='baseline' is_active=True,
    baseline.delta is None."""
    from app.services.bench import compute_bench
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    _seed_reviewed(workspace, pid, "doc1.pdf")
    _seed_eval_dir(
        workspace, pid, "20260528T010000Z",
        experiment_id=None,
        field_accuracy_macro=0.85,
        cells=[
            _cell("doc1.pdf", "supplier", "correct"),
            _cell("doc1.pdf", "total", "correct"),
        ],
    )
    out = compute_bench(workspace, pid)
    assert len(out["rows"]) == 1
    row = out["rows"][0]
    assert row["kind"] == "baseline"
    assert row["id"] == "_baseline"
    assert row["status"] == "baseline"
    assert row["is_active"] is True
    assert row["delta"] is None
    assert row["score"] == 0.85
    assert row["summary_ts"] == "20260528T010000Z"
    assert out["headline"]["best_score"] == 0.85


async def test_baseline_plus_two_experiments(workspace: Path) -> None:
    """One baseline + two experiments → 3 rows; experiment.delta correct."""
    from app.services.bench import compute_bench
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    # second prompt for one experiment
    atomic_write_json(prompt_path(workspace, pid, "pr_v2"), {
        "prompt_id": "pr_v2", "label": "v2",
        "schema": [
            {"name": "supplier", "type": "string", "description": "x", "required": False},
        ],
        "global_notes": "", "derived_from": "pr_baseline",
        "created_at": _now(), "updated_at": _now(),
    })
    _seed_reviewed(workspace, pid, "doc1.pdf")
    # baseline eval @ 0.80
    _seed_eval_dir(
        workspace, pid, "20260528T010000Z",
        experiment_id=None,
        field_accuracy_macro=0.80,
        cells=[_cell("doc1.pdf", "supplier", "correct")],
    )
    # experiment A — same axes — score 0.90
    _seed_experiment(
        workspace, pid, "ex_aaaaaaaaaaaaaa",
        prompt_id="pr_baseline", model_id="m_default",
        status="ran", score=0.90,
        summary_ts="20260528T020000Z",
    )
    _seed_eval_dir(
        workspace, pid, "20260528T020000Z",
        experiment_id="ex_aaaaaaaaaaaaaa",
        field_accuracy_macro=0.90,
        cells=[_cell("doc1.pdf", "supplier", "correct")],
        prompt_id="pr_baseline", model_id="m_default",
    )
    # experiment B — alternative prompt — score 0.70
    _seed_experiment(
        workspace, pid, "ex_bbbbbbbbbbbbbb",
        prompt_id="pr_v2", model_id="m_default",
        status="ran", score=0.70,
        summary_ts="20260528T030000Z",
    )
    _seed_eval_dir(
        workspace, pid, "20260528T030000Z",
        experiment_id="ex_bbbbbbbbbbbbbb",
        field_accuracy_macro=0.70,
        cells=[_cell("doc1.pdf", "supplier", "wrong")],
        prompt_id="pr_v2", model_id="m_default",
    )

    out = compute_bench(workspace, pid)
    assert len(out["rows"]) == 3
    by_id = {r["id"]: r for r in out["rows"]}
    assert "_baseline" in by_id
    assert "ex_aaaaaaaaaaaaaa" in by_id
    assert "ex_bbbbbbbbbbbbbb" in by_id

    # baseline delta is None
    assert by_id["_baseline"]["delta"] is None
    assert by_id["_baseline"]["score"] == 0.80
    # experiment delta vs baseline
    assert by_id["ex_aaaaaaaaaaaaaa"]["delta"] == 0.90 - 0.80
    assert by_id["ex_bbbbbbbbbbbbbb"]["delta"] == 0.70 - 0.80

    # experiment_A is_active (matches active prompt+model)
    assert by_id["ex_aaaaaaaaaaaaaa"]["is_active"] is True
    # experiment_B is NOT active (different prompt)
    assert by_id["ex_bbbbbbbbbbbbbb"]["is_active"] is False

    # headline picks best score
    assert out["headline"]["best_score"] == 0.90
    assert out["headline"]["best_prompt_id"] == "pr_baseline"
    assert out["headline"]["best_model_id"] == "m_default"


async def test_sample_filenames_lex_sorted_max_6(workspace: Path) -> None:
    """8 reviewed → take first 6 lex-sorted (with .json suffix)."""
    from app.services.bench import compute_bench
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    # Seed 8 reviewed docs with non-lex insertion order to verify sort
    for fn in ["zebra.pdf", "alpha.pdf", "delta.pdf", "bravo.pdf",
               "echo.pdf", "charlie.pdf", "foxtrot.pdf", "golf.pdf"]:
        _seed_reviewed(workspace, pid, fn)
    out = compute_bench(workspace, pid)
    assert len(out["sample_filenames"]) == 6
    # Lex-sorted with `.json` suffix (the reviewed/ basename)
    assert out["sample_filenames"] == [
        "alpha.pdf.json", "bravo.pdf.json", "charlie.pdf.json",
        "delta.pdf.json", "echo.pdf.json", "foxtrot.pdf.json",
    ]


async def test_strip_three_states(workspace: Path) -> None:
    """One row, 6 sample docs: 1 correct (strip=1), 1 wrong (strip=0),
    4 not in eval (strip=None)."""
    from app.services.bench import compute_bench
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    for fn in ["a.pdf", "b.pdf", "c.pdf", "d.pdf", "e.pdf", "f.pdf"]:
        _seed_reviewed(workspace, pid, fn)
    # eval only covers a.pdf (correct) and b.pdf (wrong), for one field 'supplier'.
    _seed_eval_dir(
        workspace, pid, "20260528T010000Z",
        experiment_id=None,
        field_accuracy_macro=0.5,
        cells=[
            _cell("a.pdf", "supplier", "correct"),
            _cell("b.pdf", "supplier", "wrong"),
            # 'total' field absent on both → absent_both for a/b
            _cell("a.pdf", "total", "absent_both"),
            _cell("b.pdf", "total", "absent_both"),
        ],
    )
    out = compute_bench(workspace, pid)
    assert len(out["rows"]) == 1
    row = out["rows"][0]
    # sample filenames are the .json basenames
    samples = out["sample_filenames"]
    assert samples == [
        "a.pdf.json", "b.pdf.json", "c.pdf.json",
        "d.pdf.json", "e.pdf.json", "f.pdf.json",
    ]
    supplier_cell = row["cells"]["supplier"]
    # strip aligned with sample_filenames
    # a.pdf → 1 (correct), b.pdf → 0 (wrong), c-f → None (no verdict)
    assert supplier_cell["strip"] == [1, 0, None, None, None, None]
    # total: a/b both absent_both → 1; c-f → None
    total_cell = row["cells"]["total"]
    assert total_cell["strip"] == [1, 1, None, None, None, None]


async def test_multi_entity_doc_strip_aggregation(workspace: Path) -> None:
    """Same (filename, field), multiple entity_idx → strip 0 if ANY wrong;
    strip 1 if ALL correct/absent_both."""
    from app.services.bench import compute_bench
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    _seed_reviewed(workspace, pid, "multi.pdf", entities=[
        {"supplier": "A"}, {"supplier": "B"},
    ])
    _seed_eval_dir(
        workspace, pid, "20260528T010000Z",
        experiment_id=None,
        field_accuracy_macro=0.5,
        cells=[
            # entity 0 correct, entity 1 wrong → strip=0
            _cell("multi.pdf", "supplier", "correct", entity_idx=0),
            _cell("multi.pdf", "supplier", "wrong", entity_idx=1),
            # 'total': entity 0 absent_both, entity 1 absent_both → strip=1
            _cell("multi.pdf", "total", "absent_both", entity_idx=0),
            _cell("multi.pdf", "total", "absent_both", entity_idx=1),
        ],
    )
    out = compute_bench(workspace, pid)
    row = out["rows"][0]
    # multi.pdf.json is the only sample → first strip slot
    assert row["cells"]["supplier"]["strip"][0] == 0
    assert row["cells"]["total"]["strip"][0] == 1


async def test_refs_counts_archived_excluded(workspace: Path) -> None:
    """3 experiments reference same prompt; one archived → refs=2."""
    from app.services.bench import compute_bench
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    # 3 experiments referencing pr_baseline (all same prompt; archived one
    # uses a 2nd model to avoid upsert collision; this test doesn't go through
    # create_experiment which would dedup).
    atomic_write_json(model_path(workspace, pid, "m_other"), {
        "model_id": "m_other", "label": "Other",
        "provider": "anthropic",
        "provider_model_id": "claude-haiku-4-5-20251001",
        "params": {}, "created_at": _now(),
    })
    atomic_write_json(model_path(workspace, pid, "m_third"), {
        "model_id": "m_third", "label": "Third",
        "provider": "anthropic",
        "provider_model_id": "claude-3-haiku",
        "params": {}, "created_at": _now(),
    })
    _seed_experiment(workspace, pid, "ex_alive11111111",
                     prompt_id="pr_baseline", model_id="m_default", status="ran")
    _seed_experiment(workspace, pid, "ex_alive22222222",
                     prompt_id="pr_baseline", model_id="m_other", status="ran")
    _seed_experiment(workspace, pid, "ex_dead111111111",
                     prompt_id="pr_baseline", model_id="m_third", status="archived")
    out = compute_bench(workspace, pid)
    # Find pr_baseline in prompts; refs should be 2 (archived not counted).
    pr = next(p for p in out["prompts"] if p["id"] == "pr_baseline")
    assert pr["refs"] == 2
    # m_default appears in one non-archived experiment → refs=1
    md = next(m for m in out["models"] if m["id"] == "m_default")
    assert md["refs"] == 1
    # m_other → refs=1, m_third → refs=0 (only archived experiment uses it)
    mo = next(m for m in out["models"] if m["id"] == "m_other")
    assert mo["refs"] == 1
    mt = next(m for m in out["models"] if m["id"] == "m_third")
    assert mt["refs"] == 0
    # Rows only include non-archived experiments
    row_ids = {r["id"] for r in out["rows"]}
    assert "ex_alive11111111" in row_ids
    assert "ex_alive22222222" in row_ids
    assert "ex_dead111111111" not in row_ids


async def test_legacy_summary_ts_fallback(workspace: Path) -> None:
    """experiment.eval.summary_ts=None but metrics/eval_<ts>/meta.json has
    experiment_id == ex_id → bench falls back to the matching eval dir and
    surfaces summary_ts + strip."""
    from app.services.bench import compute_bench
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    _seed_reviewed(workspace, pid, "doc1.pdf")
    # experiment has eval blob but no summary_ts (pre-T1 shape)
    _seed_experiment(
        workspace, pid, "ex_legacy11111111",
        prompt_id="pr_baseline", model_id="m_default",
        status="ran", score=0.75, summary_ts=None,
    )
    # write metrics/eval_<ts>/ with matching experiment_id
    _seed_eval_dir(
        workspace, pid, "20260528T040000Z",
        experiment_id="ex_legacy11111111",
        field_accuracy_macro=0.75,
        cells=[_cell("doc1.pdf", "supplier", "correct")],
    )
    out = compute_bench(workspace, pid)
    assert len(out["rows"]) == 1
    row = out["rows"][0]
    assert row["id"] == "ex_legacy11111111"
    # summary_ts was recovered from metrics/eval_<ts>/meta.json
    assert row["summary_ts"] == "20260528T040000Z"
    # strip populated (means cells.jsonl was loaded via the fallback ts)
    assert row["cells"]["supplier"]["strip"][0] == 1
