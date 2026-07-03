"""Grounding pass: pure-function reshape + lazy cache behaviour.

The grounding LLM call is stubbed (the provider adapter never runs); these
exercise the value-worklist walk, the flat-groundings → `_evidence` reshape
(including array-index collapse to locate's `[]` keys), and the cache-hit /
force semantics that decide whether the (expensive) LLM pass fires.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.tools.docs import upload_doc
from app.tools.ground import (
    _collapse,
    _reshape,
    _value_lines,
    _walk_values,
    ground_entities,
    ground_prediction,
    has_evidence,
)
from app.tools.projects import create_project
from app.tools.schema import write_schema
from app.schemas.schema_field import FieldType, SchemaField
from tests.conftest import make_provider_result


_FIXTURE = Path(__file__).parent.parent / "fixtures" / "invoice_sample.pdf"


# ── pure functions ──────────────────────────────────────────────────────────

def test_walk_values_expands_array_items() -> None:
    entity = {
        "currency": "USD",
        "totalAmount": 111.0,
        "missing": None,
        "blank": "",
        "lines": [{"name": "A"}, {"name": "B"}],
    }
    got = dict(_walk_values(entity))
    assert got["currency"] == "USD"
    assert got["totalAmount"] == "111.0"
    assert "missing" not in got  # None skipped
    assert "blank" not in got  # empty string skipped
    # array items carry concrete indices
    assert got["lines[0].name"] == "A"
    assert got["lines[1].name"] == "B"


def test_collapse_array_index_to_locate_key() -> None:
    assert _collapse("detailOfGoods[0].articleName") == "detailOfGoods[].articleName"
    assert _collapse("a[2].b[3].c") == "a[].b[].c"
    assert _collapse("currency") == "currency"


def test_reshape_keeps_concrete_row_keys_and_drops_empty_rows() -> None:
    groundings = [
        {"entity": 0, "path": "currency", "page": 1, "source": "USD"},
        # two rows of the SAME column, each with its OWN quote: must NOT collapse
        # to one `lines[].name` key (which would last-row-win and make row 0
        # inherit row 1's quote — the unitPrice→wrong-row bug).
        {"entity": 0, "path": "lines[0].name", "page": 1, "source": "Widget"},
        {"entity": 0, "path": "lines[1].name", "page": 1, "source": "Gadget"},
        {"entity": 0, "path": "totalAmount", "page": None, "source": None},  # derived → drop
        {"entity": 9, "path": "x", "page": 1, "source": "y"},  # out-of-range → drop
    ]
    ev = _reshape(groundings, n_entities=1)
    assert len(ev) == 1
    assert ev[0]["currency"] == {"page": 1, "source": "USD"}
    # concrete per-row keys preserved (locate keys evidence concrete-first)
    assert ev[0]["lines[0].name"] == {"page": 1, "source": "Widget"}
    assert ev[0]["lines[1].name"] == {"page": 1, "source": "Gadget"}
    assert "lines[].name" not in ev[0]
    assert "totalAmount" not in ev[0]


def test_reshape_always_matches_entity_count() -> None:
    assert _reshape([], n_entities=3) == [{}, {}, {}]


def test_has_evidence_detects_signal() -> None:
    assert has_evidence({"_evidence": [{"a": {"page": 1, "source": None}}]}) is True
    assert has_evidence({"_evidence": [{"a": {"page": None, "source": "x"}}]}) is True
    assert has_evidence({"_evidence": [{"a": 2}]}) is True  # legacy int form
    assert has_evidence({"_evidence": [{"a": {"page": None, "source": None}}]}) is False
    assert has_evidence({"_evidence": []}) is False
    assert has_evidence({}) is False


def test_value_lines_counts_only_present_scalars() -> None:
    txt, n = _value_lines([{"a": "x", "b": None, "rows": [{"c": "y"}]}])
    assert n == 2
    assert "path=`a`" in txt
    assert "path=`rows[0].c`" in txt


# ── ground_prediction integration (provider stubbed) ────────────────────────

def _schema() -> list[SchemaField]:
    return [
        SchemaField(name="currency", type=FieldType.STRING, description="Currency"),
        SchemaField(name="totalAmount", type=FieldType.NUMBER, description="Total"),
    ]


async def _seed(workspace: Path) -> tuple[str, str]:
    pid = (await create_project(workspace, name="g"))["slug"]
    did = (await upload_doc(workspace, pid, _FIXTURE.read_bytes(), "a.pdf"))["filename"]
    await write_schema(workspace, pid, _schema(), reason="init", allow_structural=True)
    draft = workspace / pid / "predictions" / "_draft"
    draft.mkdir(parents=True, exist_ok=True)
    (draft / f"{did}.json").write_text(
        json.dumps({"entities": [{"currency": "USD", "totalAmount": 111.0}]})
    )
    return pid, did


async def test_ground_writes_evidence_into_blob(
    workspace: Path, stub_provider: AsyncMock
) -> None:
    pid, did = await _seed(workspace)
    stub_provider.extract.return_value = make_provider_result(
        {
            "groundings": [
                {"entity": 0, "path": "currency", "page": 1, "source": "Currency: USD"},
                {"entity": 0, "path": "totalAmount", "page": None, "source": None},
            ]
        }
    )

    ev = await ground_prediction(workspace, pid, did, provider=stub_provider)
    assert ev[0]["currency"] == {"page": 1, "source": "Currency: USD"}
    assert "totalAmount" not in ev[0]  # derived → null → dropped

    blob = json.loads(
        (workspace / pid / "predictions" / "_draft" / f"{did}.json").read_text()
    )
    assert blob["_evidence"][0]["currency"]["source"] == "Currency: USD"
    # extraction payload itself is untouched
    assert blob["entities"][0]["currency"] == "USD"


async def test_ground_is_cached_second_call_skips_llm(
    workspace: Path, stub_provider: AsyncMock
) -> None:
    pid, did = await _seed(workspace)
    stub_provider.extract.return_value = make_provider_result(
        {"groundings": [{"entity": 0, "path": "currency", "page": 1, "source": "USD"}]}
    )
    await ground_prediction(workspace, pid, did, provider=stub_provider)
    assert stub_provider.extract.await_count == 1

    # second call sees cached _evidence → no new LLM pass
    await ground_prediction(workspace, pid, did, provider=stub_provider)
    assert stub_provider.extract.await_count == 1

    # force re-grounds
    await ground_prediction(workspace, pid, did, provider=stub_provider, force=True)
    assert stub_provider.extract.await_count == 2


async def test_ground_missing_blob_raises(
    workspace: Path, stub_provider: AsyncMock
) -> None:
    pid = (await create_project(workspace, name="g"))["slug"]
    did = (await upload_doc(workspace, pid, _FIXTURE.read_bytes(), "a.pdf"))["filename"]
    await write_schema(workspace, pid, _schema(), reason="init", allow_structural=True)
    with pytest.raises(FileNotFoundError):
        await ground_prediction(workspace, pid, did, provider=stub_provider)


async def test_ground_text_doc_short_circuits_no_llm(
    workspace: Path, stub_provider: AsyncMock
) -> None:
    """Text-shaped docs never render grounding (no coordinate overlay), so
    ``ground_entities`` must return empty evidence WITHOUT spending the
    provider call — the eager produce path otherwise pays one wasted LLM
    round trip per prediction (per rule × doc in judgment-style projects)."""
    pid = (await create_project(workspace, name="g"))["slug"]
    did = (
        await upload_doc(workspace, pid, b'{"a": 3, "b": 4, "c": 12}', "mul.json")
    )["filename"]

    ev = await ground_entities(
        workspace, pid, did,
        [{"pass": False, "reason": "a×b=12，c=10，差值为 2"}],
        provider=stub_provider, model_id="deepseek-v4-flash",
    )

    assert ev == [{}]
    stub_provider.extract.assert_not_awaited()
