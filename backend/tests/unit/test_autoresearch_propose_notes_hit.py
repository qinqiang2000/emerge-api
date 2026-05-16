# backend/tests/unit/test_autoresearch_propose_notes_hit.py
"""Phase B autoresearch proposer `notes_hit` declaration + sanity filter.

Verifies:
    * propose_schema returns the new 4-tuple (proposed, rationale,
      validated_notes_hit, filtered_notes_hit).
    * _validate_notes_hit drops entries whose filename is missing from
      reviewed_dict.
    * _validate_notes_hit drops entries whose field is not in proposed_schema.
    * _validate_notes_hit drops entries whose description text is unchanged.
    * _save_candidate_turn persists both arrays.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.jobs.autoresearch import (
    PROPOSER_RESPONSE_SCHEMA,
    PROPOSER_SYSTEM_PROMPT,
    _save_candidate_turn,
    _validate_notes_hit,
    propose_schema,
)
from app.provider.base import ProviderResult
from app.schemas.schema_field import FieldType, SchemaField
from app.schemas.score import FieldScore, ScoreResult


def _f(name: str, desc: str = "x") -> SchemaField:
    return SchemaField(name=name, type=FieldType.STRING, description=desc)


def test_response_schema_now_includes_notes_hit() -> None:
    assert "notes_hit" in PROPOSER_RESPONSE_SCHEMA["properties"]
    assert PROPOSER_RESPONSE_SCHEMA["properties"]["notes_hit"]["type"] == "array"
    # Not required — proposer may omit when no notes drove changes.
    assert "notes_hit" not in PROPOSER_RESPONSE_SCHEMA.get("required", [])


def test_system_prompt_mentions_notes_hit() -> None:
    assert "notes_hit" in PROPOSER_SYSTEM_PROMPT
    assert "Hallucinated" in PROPOSER_SYSTEM_PROMPT


def test_validate_notes_hit_keeps_valid() -> None:
    baseline = [_f("buyer_name", "old desc"), _f("seller_name", "unchanged")]
    proposed = [_f("buyer_name", "new desc"), _f("seller_name", "unchanged")]
    reviewed = {"inv-042.pdf": [{}]}
    validated, filtered = _validate_notes_hit(
        ["inv-042.pdf.buyer_name"], baseline, proposed, reviewed,
    )
    assert validated == ["inv-042.pdf.buyer_name"]
    assert filtered == []


def test_validate_notes_hit_drops_unknown_filename() -> None:
    baseline = [_f("buyer_name", "old")]
    proposed = [_f("buyer_name", "new")]
    reviewed = {"inv-042.pdf": [{}]}
    validated, filtered = _validate_notes_hit(
        ["other-doc.pdf.buyer_name"], baseline, proposed, reviewed,
    )
    assert validated == []
    assert filtered == ["other-doc.pdf.buyer_name"]


def test_validate_notes_hit_drops_unknown_field() -> None:
    baseline = [_f("buyer_name", "old")]
    proposed = [_f("buyer_name", "new")]
    reviewed = {"inv-042.pdf": [{}]}
    validated, filtered = _validate_notes_hit(
        ["inv-042.pdf.no_such_field"], baseline, proposed, reviewed,
    )
    assert validated == []
    assert filtered == ["inv-042.pdf.no_such_field"]


def test_validate_notes_hit_drops_unchanged_description() -> None:
    baseline = [_f("buyer_name", "same desc")]
    proposed = [_f("buyer_name", "same desc")]
    reviewed = {"inv-042.pdf": [{}]}
    validated, filtered = _validate_notes_hit(
        ["inv-042.pdf.buyer_name"], baseline, proposed, reviewed,
    )
    assert validated == []
    assert filtered == ["inv-042.pdf.buyer_name"]


def test_validate_notes_hit_drops_malformed_entries() -> None:
    baseline = [_f("x")]
    proposed = [_f("x", "changed")]
    reviewed = {"inv.pdf": [{}]}
    validated, filtered = _validate_notes_hit(
        ["no_dot_here", "", ".missing_filename", "missing_field.", ""],
        baseline, proposed, reviewed,
    )
    assert validated == []
    assert len(filtered) == 5


def test_validate_notes_hit_splits_on_last_dot() -> None:
    """Filenames legitimately contain dots (e.g. `inv-042.pdf`); the split
    must happen at the LAST dot so `inv-042.pdf.buyer_name` reads as
    (`inv-042.pdf`, `buyer_name`)."""
    baseline = [_f("buyer_name", "a")]
    proposed = [_f("buyer_name", "b")]
    reviewed = {"inv-042.pdf": [{}]}
    validated, _ = _validate_notes_hit(
        ["inv-042.pdf.buyer_name"], baseline, proposed, reviewed,
    )
    assert validated == ["inv-042.pdf.buyer_name"]


async def test_propose_schema_returns_4_tuple_with_validated_notes_hit() -> None:
    schema = [_f("buyer_name", "old")]
    new_blob = {
        "fields": [{"name": "buyer_name", "type": "string", "description": "new tight desc"}],
        "rationale": "tightened",
        "notes_hit": ["inv-042.pdf.buyer_name", "ghost.pdf.no_field"],
    }
    provider = AsyncMock()
    provider.extract.return_value = ProviderResult(raw_json=new_blob, model_id="stub")
    proposed, rationale, validated, filtered = await propose_schema(
        provider=provider, model_id="stub", schema=schema,
        reviewed={"inv-042.pdf": [{}]},
        predictions={}, per_field=[], notes={},
    )
    assert proposed[0].description == "new tight desc"
    assert rationale == "tightened"
    assert validated == ["inv-042.pdf.buyer_name"]
    # The ghost.pdf hit is filtered (unknown filename).
    assert filtered == ["ghost.pdf.no_field"]


async def test_propose_schema_handles_missing_notes_hit() -> None:
    """Proposer may legitimately omit `notes_hit` when no notes drove changes."""
    schema = [_f("x", "old")]
    new_blob = {
        "fields": [{"name": "x", "type": "string", "description": "new"}],
        "rationale": "improved by sample errors only",
    }
    provider = AsyncMock()
    provider.extract.return_value = ProviderResult(raw_json=new_blob, model_id="stub")
    proposed, rationale, validated, filtered = await propose_schema(
        provider=provider, model_id="stub", schema=schema,
        reviewed={}, predictions={}, per_field=[], notes={},
    )
    assert validated == []
    assert filtered == []


def test_save_candidate_turn_persists_notes_hit_arrays(tmp_path: Path) -> None:
    """The candidate turn JSON must carry both `notes_hit` and
    `notes_hit_filtered` for accept_candidate (and offline monitoring)."""
    schema = [_f("buyer_name", "new")]
    score = ScoreResult(
        n_docs=1,
        n_reviewed=1,
        macro_f1=0.8,
        per_field=[FieldScore(field="buyer_name", precision=0.8, recall=0.8, f1=0.8, tp=1, fp=0, fn=0, support=1)],
        errors=[],
        ts="2026-05-16T10:00:00Z",
        schema_field_count=1,
    )
    target = _save_candidate_turn(
        workspace=tmp_path,
        project_id="p_a", job_id="j_x", turn=2,
        schema=schema, score_result=score, predictions={},
        rationale="r", parent_turn=0,
        notes_hit=["inv.pdf.buyer_name"],
        notes_hit_filtered=["ghost.pdf.foo"],
    )
    blob = json.loads(target.read_text())
    assert blob["notes_hit"] == ["inv.pdf.buyer_name"]
    assert blob["notes_hit_filtered"] == ["ghost.pdf.foo"]
