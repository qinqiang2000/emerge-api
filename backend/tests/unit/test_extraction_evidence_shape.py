"""Tests for the field-source-grounding evidence shape evolution.

`ExtractionOutput.evidence` accepts both the legacy `{field: int|null}` wire
shape and the new `{field: {page, source}}` shape, normalizing both into the
internal `FieldEvidence` form. The page-only view stays backward compatible.
"""

from __future__ import annotations

import pytest

from app.schemas.extraction import (
    ExtractionOutput,
    FieldEvidence,
    evidence_page,
    evidence_source,
)


def test_evidence_absent_is_empty_view():
    out = ExtractionOutput(entities=[{"a": 1}])
    assert out.evidence is None
    assert out.evidence_pages == []
    assert out.evidence_entries == []


def test_evidence_new_shape_with_source():
    out = ExtractionOutput(
        entities=[{"total": 100}],
        _evidence=[{"total": {"page": 2, "source": "TOTAL 100.00"}}],
    )
    # page-only view stays backward compatible
    assert out.evidence_pages[0]["total"] == 2
    # new entries view carries source as FieldEvidence
    entry = out.evidence_entries[0]
    assert isinstance(entry["total"], FieldEvidence)
    assert entry["total"].page == 2
    assert entry["total"].source == "TOTAL 100.00"


def test_evidence_legacy_int_coerced():
    out = ExtractionOutput(entities=[{"total": 100}], _evidence=[{"total": 3}])
    assert out.evidence_pages[0]["total"] == 3
    entry = out.evidence_entries[0]
    assert entry["total"].page == 3
    assert entry["total"].source is None


def test_evidence_null_for_derived():
    out = ExtractionOutput(
        entities=[{"sum": 300}],
        _evidence=[{"sum": {"page": None, "source": None}}],
    )
    assert out.evidence_pages[0]["sum"] is None
    assert out.evidence_entries[0]["sum"].source is None


def test_evidence_length_invariant_still_enforced():
    with pytest.raises(ValueError):
        ExtractionOutput(
            entities=[{"a": 1}, {"b": 2}],
            _evidence=[{"a": 1}],  # length 1 != 2 entities
        )


def test_round_trip_serializes_to_wire_alias():
    out = ExtractionOutput(
        entities=[{"x": 1}],
        _evidence=[{"x": {"page": 1, "source": "X"}}],
    )
    dumped = out.model_dump(by_alias=True)
    assert "_evidence" in dumped
    assert dumped["_evidence"][0]["x"]["page"] == 1
    assert dumped["_evidence"][0]["x"]["source"] == "X"


def test_accessors_tolerate_raw_shapes():
    # raw int entry
    assert evidence_page({"x": 5}, "x") == 5
    assert evidence_source({"x": 5}, "x") is None
    # raw dict entry
    assert evidence_page({"x": {"page": 4, "source": "q"}}, "x") == 4
    assert evidence_source({"x": {"page": 4, "source": "q"}}, "x") == "q"
    # FieldEvidence entry
    fe = {"x": FieldEvidence(page=7, source="s")}
    assert evidence_page(fe, "x") == 7
    assert evidence_source(fe, "x") == "s"
    # null / missing / None entry
    assert evidence_page({"x": None}, "x") is None
    assert evidence_page({}, "x") is None
    assert evidence_source(None, "x") is None
