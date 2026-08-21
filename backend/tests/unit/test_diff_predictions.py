"""T9 — `diff_predictions`: the no-ground-truth branch of /compare.

Plan: docs/superpowers/plans/2026-08-20-compare-for-pm.md §4 T9.

Two invariants matter more than the shape here:

1. **No score, ever.** Without `reviewed/` there is no accuracy — the agreement
   rate between two models is not accuracy (HANDOFF「判断陷阱 1」). The only
   honest product is "which cells disagree", a queue to adjudicate INTO ground
   truth. `test_result_carries_no_score_keys` locks that red line by walking the
   whole payload, so a future "just add a quick 一致率" cannot land quietly.
2. **Entity-count mismatches are announced, not swallowed.** A model that
   under-splits a doc (3 entities → 1) looks great if you silently grade the
   overlap. The overlap is still aligned, but the mismatch is reported.

Equivalence is the scorer's (`normalize_equivalent`), so `1,234.00` vs `1234`
is not a finding — a work queue full of false positives is a work queue nobody
finishes.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.diff_predictions import DiffSourceError, diff_predictions
from app.tools.projects import create_project
from app.tools.schema import write_schema
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import experiment_predictions_dir, predictions_draft_dir


EX_ID = "ex_abc123def456"


def _schema() -> list[SchemaField]:
    return [
        # ★ important fields — the PM's time should go here first.
        SchemaField(
            name="invoice_no", type=FieldType.STRING, description="d",
            required=True,
        ),
        SchemaField(
            name="total", type=FieldType.NUMBER, description="d", required=True,
        ),
        SchemaField(name="memo", type=FieldType.STRING, description="d"),
    ]


async def _project(workspace: Path, name: str) -> str:
    slug = (await create_project(workspace, name=name))["slug"]
    await write_schema(
        workspace, slug, _schema(), reason="t", allow_structural=True,
    )
    return slug


def _write_draft(
    workspace: Path, slug: str, filename: str, entities: list[dict[str, Any]],
) -> None:
    d = predictions_draft_dir(workspace, slug)
    d.mkdir(parents=True, exist_ok=True)
    atomic_write_json(d / f"{filename}.json", {"entities": entities})


def _write_experiment(
    workspace: Path,
    slug: str,
    filename: str,
    entities: list[dict[str, Any]],
    experiment_id: str = EX_ID,
) -> None:
    d = experiment_predictions_dir(workspace, slug, experiment_id)
    d.mkdir(parents=True, exist_ok=True)
    atomic_write_json(d / f"{filename}.json", {"entities": entities})


async def _diff_two_drafts(
    workspace: Path,
    name: str,
    a_entities: list[dict[str, Any]],
    b_entities: list[dict[str, Any]],
    *,
    filename: str = "x.pdf",
) -> dict[str, Any]:
    """Seed side A into `_draft` and side B into an experiment, then diff."""
    slug = await _project(workspace, name)
    _write_draft(workspace, slug, filename, a_entities)
    _write_experiment(workspace, slug, filename, b_entities)
    return await diff_predictions(workspace, slug, "_draft", EX_ID)


# ── 1. equivalence normalisation must not manufacture disagreements ─────────


async def test_equivalent_number_spellings_are_not_a_disagreement(
    workspace: Path,
) -> None:
    """`1,234.00` vs `1234` on a NUMBER field is one value with two spellings.
    Reported as a disagreement it would send the PM to adjudicate a non-issue —
    which is why equivalence reuses `app/eval/normalize.py` rather than `==`."""
    out = await _diff_two_drafts(
        workspace, "eq-number",
        [{"invoice_no": "INV-1", "total": "1,234.00", "memo": "m"}],
        [{"invoice_no": "INV-1", "total": "1234", "memo": "m"}],
    )
    assert out["n_diff"] == 0, out["cells"]
    assert out["by_field"] == []
    assert out["n_cells"] == 3  # 1 doc × 1 entity × 3 fields, all aligned


async def test_both_sides_blank_is_not_a_disagreement(workspace: Path) -> None:
    """None vs "" is "neither side found a value" under the scorer's lenient
    absence policy — nothing to adjudicate, but the cell still counts as
    aligned."""
    out = await _diff_two_drafts(
        workspace, "eq-blank",
        [{"invoice_no": "INV-1", "total": 1, "memo": None}],
        [{"invoice_no": "INV-1", "total": 1, "memo": ""}],
    )
    assert out["n_diff"] == 0, out["cells"]
    assert out["n_cells"] == 3


# ── 2. entity-count mismatch must be announced ──────────────────────────────


async def test_entity_count_mismatch_is_reported_and_overlap_still_aligned(
    workspace: Path,
) -> None:
    """Side A split the doc into 3 entities, side B into 1. The overlap (idx 0)
    is compared as usual, but the mismatch is stated out loud — silently
    comparing the overlap flatters whichever side under-split."""
    out = await _diff_two_drafts(
        workspace, "entity-mismatch",
        [
            {"invoice_no": "INV-1", "total": 1, "memo": "first"},
            {"invoice_no": "INV-2", "total": 2, "memo": "second"},
            {"invoice_no": "INV-3", "total": 3, "memo": "third"},
        ],
        [{"invoice_no": "INV-1", "total": 1, "memo": "ONLY"}],
    )
    assert out["entity_count_mismatch"] == [
        {"filename": "x.pdf", "n_a": 3, "n_b": 1},
    ]
    # Overlap only: 1 entity × 3 fields.
    assert out["n_cells"] == 3
    assert [(c["field"], c["entity_idx"]) for c in out["cells"]] == [("memo", 0)]
    assert out["cells"][0]["a"] == "first"
    assert out["cells"][0]["b"] == "ONLY"


async def test_doc_present_on_one_side_only_is_reported_not_dropped(
    workspace: Path,
) -> None:
    """A doc one side never extracted is the degenerate mismatch (n=0 vs n=k).
    It must surface — dropping it is the same silent-favouritism bug."""
    slug = await _project(workspace, "one-sided-doc")
    _write_draft(workspace, slug, "both.pdf", [{"invoice_no": "INV-1"}])
    _write_experiment(workspace, slug, "both.pdf", [{"invoice_no": "INV-1"}])
    _write_draft(workspace, slug, "only-a.pdf", [{"invoice_no": "INV-9"}])

    out = await diff_predictions(workspace, slug, "_draft", EX_ID)
    assert out["entity_count_mismatch"] == [
        {"filename": "only-a.pdf", "n_a": 1, "n_b": 0},
    ]
    assert out["n_cells"] == 3  # only the shared doc's single entity aligns
    assert out["n_diff"] == 0


# ── 3. required grouping ────────────────────────────────────────────────────


async def test_required_field_disagreements_are_counted_separately(
    workspace: Path,
) -> None:
    """`SchemaField.required` is the ★重要字段 marker: the PM's adjudication
    time goes to those first, so they get their own count and sort first."""
    out = await _diff_two_drafts(
        workspace, "required-grouping",
        [{"invoice_no": "INV-1", "total": 1, "memo": "left"}],
        [{"invoice_no": "INV-2", "total": 1, "memo": "right"}],
    )
    assert out["n_diff"] == 2
    assert out["n_diff_required"] == 1

    assert out["by_field"] == [
        {"field": "invoice_no", "n_diff": 1, "required": True},
        {"field": "memo", "n_diff": 1, "required": False},
    ]
    # required cells lead the queue, whatever the field name's sort order
    assert [c["field"] for c in out["cells"]] == ["invoice_no", "memo"]
    assert [c["required"] for c in out["cells"]] == [True, False]
    assert out["cells"][0]["a"] == "INV-1"
    assert out["cells"][0]["b"] == "INV-2"


# ── 4. red line: no score, no percentage, ever ──────────────────────────────


_FORBIDDEN_KEY_WORDS = (
    "accuracy", "score", "rate", "percent", "pct", "ratio",
    "agreement", "consistency", "f1", "precision", "recall",
)


def _walk(node: Any) -> Iterator[tuple[str, Any]]:
    if isinstance(node, dict):
        for k, v in node.items():
            yield k, v
            yield from _walk(v)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


async def test_result_carries_no_score_keys(workspace: Path) -> None:
    """RED LINE (plan §4): without ground truth there is no accuracy. Two models
    agreeing says nothing about either being right. This payload therefore
    carries counts and cells only — never a ratio, a percentage or a float."""
    out = await _diff_two_drafts(
        workspace, "no-scores",
        [{"invoice_no": "INV-1", "total": 1, "memo": "left"}],
        [{"invoice_no": "INV-2", "total": 2, "memo": "right"}],
    )
    assert out["n_diff"] == 3  # sanity: this fixture really does disagree

    offenders = [
        k for k, _v in _walk(out)
        if any(w in k.lower() for w in _FORBIDDEN_KEY_WORDS)
    ]
    assert not offenders, (
        f"diff_predictions grew score-shaped keys {offenders} — an agreement "
        f"rate is not an accuracy; the no-GT surface reports counts only."
    )
    floats = [(k, v) for k, v in _walk(out) if isinstance(v, float)]
    assert not floats, (
        f"diff_predictions returned float values {floats} — every number here "
        f"is a count; a float is how a percentage sneaks back in."
    )
    assert set(out) == {
        "n_cells", "n_diff", "n_diff_required",
        "by_field", "cells", "entity_count_mismatch",
    }


# ── 5. the boring case must be boring ───────────────────────────────────────


async def test_identical_sides_yield_zero_diff(workspace: Path) -> None:
    """Two sides that agree everywhere is a valid, non-exceptional answer:
    an empty queue, not an error."""
    entities = [
        {"invoice_no": "INV-1", "total": 100, "memo": "same"},
        {"invoice_no": "INV-2", "total": 200, "memo": "same"},
    ]
    out = await _diff_two_drafts(
        workspace, "identical", entities, [dict(e) for e in entities],
    )
    assert out["n_diff"] == 0
    assert out["n_diff_required"] == 0
    assert out["cells"] == []
    assert out["by_field"] == []
    assert out["entity_count_mismatch"] == []
    assert out["n_cells"] == 6  # 2 entities × 3 fields


# ── 6. source resolution is a whitelist ─────────────────────────────────────


@pytest.mark.parametrize("bad", ["../../etc", "_pending", "reviewed", "ex_BAD"])
async def test_unknown_source_is_rejected(workspace: Path, bad: str) -> None:
    """`a` / `b` reach the filesystem, and both arrive from an HTTP query
    string. Only `_draft` and a well-formed experiment id are accepted."""
    slug = await _project(workspace, f"bad-source-{abs(hash(bad)) % 1000}")
    with pytest.raises(DiffSourceError) as exc:
        await diff_predictions(workspace, slug, "_draft", bad)
    assert exc.value.error_code == "diff_source_invalid"


async def test_missing_source_dir_is_a_typed_error(workspace: Path) -> None:
    slug = await _project(workspace, "missing-source")
    _write_draft(workspace, slug, "x.pdf", [{"invoice_no": "INV-1"}])
    with pytest.raises(DiffSourceError) as exc:
        await diff_predictions(workspace, slug, "_draft", EX_ID)
    assert exc.value.error_code == "diff_source_not_found"


async def test_unknown_project_is_a_typed_error(workspace: Path) -> None:
    with pytest.raises(DiffSourceError) as exc:
        await diff_predictions(workspace, "nope", "_draft", EX_ID)
    assert exc.value.error_code == "project_not_found"


# ── 7. HTTP twin (tool ↔ HTTP symmetry) ─────────────────────────────────────


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("EMERGE_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("EMERGE_TEST_MODE", "1")
    monkeypatch.chdir(tmp_path)
    return TestClient(app)


def test_http_twin_returns_the_same_payload(
    client: TestClient, tmp_path: Path,
) -> None:
    slug = asyncio.run(_project(tmp_path, "http-twin"))
    _write_draft(tmp_path, slug, "x.pdf", [{"invoice_no": "INV-1", "memo": "L"}])
    _write_experiment(tmp_path, slug, "x.pdf", [{"invoice_no": "INV-1", "memo": "R"}])

    r = client.get(f"/lab/projects/{slug}/compare/diff", params={"a": "_draft", "b": EX_ID})
    assert r.status_code == 200
    assert r.json() == asyncio.run(diff_predictions(tmp_path, slug, "_draft", EX_ID))
    assert r.json()["n_diff"] == 1


def test_http_twin_rejects_an_unknown_source(
    client: TestClient, tmp_path: Path,
) -> None:
    slug = asyncio.run(_project(tmp_path, "http-bad-source"))
    r = client.get(
        f"/lab/projects/{slug}/compare/diff", params={"a": "_draft", "b": "../etc"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error_code"] == "diff_source_invalid"
