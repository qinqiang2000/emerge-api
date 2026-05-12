from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.prompt_variant import PromptVariant
from app.schemas.schema_field import FieldType, SchemaField


def _field(name: str = "invoice_no") -> SchemaField:
    return SchemaField(name=name, type=FieldType.STRING, description="d")


def test_minimal_prompt_variant() -> None:
    pv = PromptVariant(
        prompt_id="pr_baseline",
        label="Baseline",
        schema=[_field()],
        created_at="2026-05-12T00:00:00+00:00",
        updated_at="2026-05-12T00:00:00+00:00",
    )
    assert pv.global_notes == ""
    assert pv.derived_from is None
    assert pv.schema[0].name == "invoice_no"


def test_round_trip_dump_load() -> None:
    pv = PromptVariant(
        prompt_id="pr_uk",
        label="UK adaptation",
        schema=[_field("supplier_county")],
        global_notes="UK uses county not state.",
        derived_from="pr_baseline",
        created_at="2026-05-12T00:00:00+00:00",
        updated_at="2026-05-12T00:00:00+00:00",
    )
    blob = pv.model_dump(mode="json")
    restored = PromptVariant(**blob)
    assert restored == pv


def test_cross_project_derived_from_string_ok() -> None:
    pv = PromptVariant(
        prompt_id="pr_b_from_us",
        label="from US",
        schema=[_field()],
        derived_from="p_us_invoice/pr_baseline",
        created_at="2026-05-12T00:00:00+00:00",
        updated_at="2026-05-12T00:00:00+00:00",
    )
    assert pv.derived_from == "p_us_invoice/pr_baseline"


def test_empty_schema_allowed() -> None:
    # New projects start with empty schema; not an error at model level
    pv = PromptVariant(
        prompt_id="pr_baseline",
        label="Empty",
        schema=[],
        created_at="2026-05-12T00:00:00+00:00",
        updated_at="2026-05-12T00:00:00+00:00",
    )
    assert pv.schema == []


def test_unknown_field_rejected() -> None:
    # extra="forbid" — typos in field names should error so we catch drift
    with pytest.raises(ValidationError):
        PromptVariant(
            prompt_id="pr_baseline",
            label="x",
            schema=[],
            created_at="2026-05-12T00:00:00+00:00",
            updated_at="2026-05-12T00:00:00+00:00",
            descriptions="oops typo",  # type: ignore[call-arg]
        )
