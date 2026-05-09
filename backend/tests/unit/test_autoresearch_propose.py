from app.jobs.autoresearch import (
    PROPOSER_RESPONSE_SCHEMA,
    PROPOSER_SYSTEM_PROMPT,
    build_proposer_user_text,
)
from app.schemas.schema_field import FieldType, SchemaField


def _f(name: str, desc: str) -> SchemaField:
    return SchemaField(name=name, type=FieldType.STRING, description=desc)


def test_proposer_response_schema_shape() -> None:
    s = PROPOSER_RESPONSE_SCHEMA
    assert s["type"] == "object"
    assert "fields" in s["properties"]
    assert "rationale" in s["properties"]
    assert "fields" in s["required"]


def test_proposer_system_prompt_forbids_structural_changes() -> None:
    # The prompt must explicitly tell the model NOT to add/remove/rename/retype.
    prompt = PROPOSER_SYSTEM_PROMPT
    assert "description" in prompt.lower()
    forbidden = ["add", "remove", "rename", "retype"]
    for kw in forbidden:
        assert kw in prompt.lower(), f"prompt missing guard against {kw!r}"


def test_proposer_user_text_includes_schema_and_scores() -> None:
    schema = [_f("invoice_no", "the number of the invoice")]
    reviewed = {"d_a": [{"invoice_no": "INV-1"}]}
    predictions = {"d_a": [{"invoice_no": "WRONG"}]}
    notes = {"d_a": {"invoice_no": "official is INV-1, not WRONG"}}
    per_field_summary = [{"field": "invoice_no", "f1": 0.0, "tp": 0, "fp": 1, "fn": 1}]

    text = build_proposer_user_text(
        schema=schema,
        reviewed=reviewed,
        predictions=predictions,
        per_field=per_field_summary,
        notes=notes,
    )
    assert "invoice_no" in text
    assert "WRONG" in text
    assert "INV-1" in text
    assert "official is INV-1" in text
    # f1 number visible
    assert "0.0" in text or "0.00" in text


def test_proposer_user_text_includes_no_notes_section_when_empty() -> None:
    schema = [_f("x", "a field")]
    text = build_proposer_user_text(
        schema=schema, reviewed={}, predictions={}, per_field=[], notes={}
    )
    assert "user notes" not in text.lower() or "(none)" in text.lower()


from unittest.mock import AsyncMock

import pytest

from app.jobs.autoresearch import ProposerStructuralChangeError, propose_schema
from app.provider.base import ProviderResult


async def test_propose_schema_returns_revised_descriptions() -> None:
    schema = [_f("invoice_no", "old desc")]
    new_blob = {
        "fields": [{"name": "invoice_no", "type": "string", "description": "new sharper desc"}],
        "rationale": "tightened format guidance",
    }
    provider = AsyncMock()
    provider.extract.return_value = ProviderResult(raw_json=new_blob, model_id="stub")

    proposed, rationale = await propose_schema(
        provider=provider, model_id="stub", schema=schema,
        reviewed={}, predictions={}, per_field=[], notes={},
    )
    assert len(proposed) == 1
    assert proposed[0].name == "invoice_no"
    assert proposed[0].description == "new sharper desc"
    assert rationale == "tightened format guidance"


async def test_propose_schema_rejects_added_field() -> None:
    schema = [_f("invoice_no", "old desc")]
    bad_blob = {
        "fields": [
            {"name": "invoice_no", "type": "string", "description": "new"},
            {"name": "snuck_in", "type": "string", "description": "extra"},
        ],
        "rationale": "tried to add field",
    }
    provider = AsyncMock()
    provider.extract.return_value = ProviderResult(raw_json=bad_blob, model_id="stub")
    with pytest.raises(ProposerStructuralChangeError):
        await propose_schema(
            provider=provider, model_id="stub", schema=schema,
            reviewed={}, predictions={}, per_field=[], notes={},
        )


async def test_propose_schema_rejects_renamed_field() -> None:
    schema = [_f("invoice_no", "x")]
    bad_blob = {
        "fields": [{"name": "invoice_number", "type": "string", "description": "y"}],
        "rationale": "renamed",
    }
    provider = AsyncMock()
    provider.extract.return_value = ProviderResult(raw_json=bad_blob, model_id="stub")
    with pytest.raises(ProposerStructuralChangeError):
        await propose_schema(
            provider=provider, model_id="stub", schema=schema,
            reviewed={}, predictions={}, per_field=[], notes={},
        )


async def test_propose_schema_rejects_retyped_field() -> None:
    schema = [_f("invoice_no", "x")]
    bad_blob = {
        "fields": [{"name": "invoice_no", "type": "number", "description": "y"}],
        "rationale": "retyped",
    }
    provider = AsyncMock()
    provider.extract.return_value = ProviderResult(raw_json=bad_blob, model_id="stub")
    with pytest.raises(ProposerStructuralChangeError):
        await propose_schema(
            provider=provider, model_id="stub", schema=schema,
            reviewed={}, predictions={}, per_field=[], notes={},
        )
