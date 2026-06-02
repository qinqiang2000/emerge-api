"""Focused (field-scoped) tune: scoped headline, description-lock, corrections
signal, and the per-field correction counter lifecycle."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.jobs import autoresearch as ar
from app.jobs.autoresearch import (
    _load_corrections_for_fields,
    _scoped_headline,
    build_proposer_user_text,
    propose_schema,
)
from app.schemas.schema_field import FieldType, SchemaField
from app.schemas.score import FieldScore, ScoreResult
from app.tools.projects import (
    bump_corrections_by_field_in_blob,
    consume_corrections_after_tune,
)
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import project_json_path, reviewed_dir


def _f(name: str, desc: str = "d") -> SchemaField:
    return SchemaField(name=name, type=FieldType.STRING, description=desc)


def _score(per: dict[str, float]) -> ScoreResult:
    return ScoreResult(
        n_docs=1, n_reviewed=1,
        field_accuracy_macro=sum(per.values()) / len(per),
        macro_f1=None,
        per_field=[
            FieldScore(field=k, accuracy=v, correct=1, total=1) for k, v in per.items()
        ],
        errors=[], ts="t", schema_field_count=len(per),
    )


def test_scoped_headline_focuses_on_target() -> None:
    sr = _score({"a": 0.4, "b": 0.9, "c": 1.0})
    # No focus → global macro.
    assert _scoped_headline(sr, None) == pytest.approx((0.4 + 0.9 + 1.0) / 3)
    # Focus on one field → just that field.
    assert _scoped_headline(sr, ["a"]) == pytest.approx(0.4)
    # Focus on two → their mean, ignoring the rest.
    assert _scoped_headline(sr, ["a", "b"]) == pytest.approx((0.4 + 0.9) / 2)


def test_scoped_headline_falls_back_when_target_ungraded() -> None:
    sr = _score({"a": 0.4, "b": 0.9})
    # Target field carries no signal this run → fall back to global, not 0.0.
    assert _scoped_headline(sr, ["missing"]) == pytest.approx((0.4 + 0.9) / 2)


def test_load_corrections_for_fields(workspace: Path) -> None:
    slug = "p_aaaaaaaaaaaa"
    rdir = reviewed_dir(workspace, slug)
    rdir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(rdir / "inv-1.pdf.json", {
        "entities": [{}],
        "_corrections": {
            "salesOrderNumber": {"before": "K/P006-D1515926", "after": "K/P006"},
            "currency": {"before": "RM", "after": "MYR"},
        },
    })
    out = _load_corrections_for_fields(workspace, slug, ["salesOrderNumber"])
    assert "salesOrderNumber" in out
    assert "currency" not in out  # not a target
    assert out["salesOrderNumber"][0]["after"] == "K/P006"


class _FakeProvider:
    """Returns a proposal that rewrites EVERY field's description — the loop
    must lock non-target fields back to baseline."""

    def __init__(self, fields: list[SchemaField]) -> None:
        self._fields = fields

    async def extract(self, **kwargs):  # noqa: ANN003
        return SimpleNamespace(raw_json={
            "rationale": "rewrote everything",
            "fields": [
                {"name": f.name, "type": f.type.value, "description": f"NEW {f.name}"}
                for f in self._fields
            ],
            "notes_hit": [],
        })


async def test_propose_schema_locks_non_target_descriptions() -> None:
    schema = [_f("a", "orig-a"), _f("b", "orig-b"), _f("c", "orig-c")]
    proposed, _rat, _hit, _filt = await propose_schema(
        provider=_FakeProvider(schema), model_id="stub", schema=schema,
        reviewed={}, predictions={}, per_field=[], notes={},
        target_fields=["b"],
    )
    by = {f.name: f.description for f in proposed}
    assert by["b"] == "NEW b"        # target moved
    assert by["a"] == "orig-a"       # locked
    assert by["c"] == "orig-c"       # locked


def test_proposer_user_text_focus_filters() -> None:
    schema = [_f("a"), _f("b")]
    text = build_proposer_user_text(
        schema=schema,
        reviewed={"inv": [{"a": "x", "b": "y"}]},
        predictions={"inv": [{"a": "wrong", "b": "y"}]},
        per_field=[{"field": "a", "accuracy": 0.5}, {"field": "b", "accuracy": 0.9}],
        notes={"inv": {"a": "fix a", "b": "fix b"}},
        target_fields=["a"],
        corrections={"a": [{"before": "wrong", "after": "x"}]},
    )
    assert "=== focus ===" in text
    assert "Only improve the description(s) of: a" in text
    # b's note / score / error must be filtered out under focus.
    assert "fix b" not in text
    assert "inv.b" not in text
    assert "corrected to 'x'" in text


def test_bump_and_consume_corrections_by_field() -> None:
    blob: dict = {}
    bump_corrections_by_field_in_blob(blob, ["a", "b"])
    bump_corrections_by_field_in_blob(blob, ["a"])
    assert blob["corrections_by_field"] == {"a": 2, "b": 1}


async def test_consume_corrections_scoped_vs_full(workspace: Path) -> None:
    slug = "p_aaaaaaaaaaaa"
    pj = project_json_path(workspace, slug)
    pj.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(pj, {
        "corrections_since_tune": 3,
        "corrections_by_field": {"a": 2, "b": 1},
    })
    # Focused accept on `a` → only a's backlog retires.
    await consume_corrections_after_tune(workspace, slug, ["a"])
    blob = json.loads(pj.read_text())
    assert blob["corrections_by_field"] == {"b": 1}
    assert blob["corrections_since_tune"] == 1
    # Full accept (no target_fields) → clear everything.
    await consume_corrections_after_tune(workspace, slug, None)
    blob = json.loads(pj.read_text())
    assert blob["corrections_by_field"] == {}
    assert blob["corrections_since_tune"] == 0
