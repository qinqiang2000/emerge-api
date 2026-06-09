"""L1/L2 pair judgement (app/match/judge.py)."""
from __future__ import annotations

from app.match.judge import judge_pair, key_match
from app.provider.base import ProviderResult
from app.schemas.match import KeyMapping, Tol


def _km(anchor, source, tol):
    return KeyMapping(anchor=anchor, source=source, tol=tol)


# --- key_match (the tolerance comparators) ----------------------------------

def test_key_match_exact():
    assert key_match("ORD-123", "ord-123", Tol(type="exact")) is True   # casefold
    assert key_match("INV/2026", "inv2026", Tol(type="exact")) is True  # non-word punct strip
    assert key_match("ORD-123", "ORD-999", Tol(type="exact")) is False


def test_key_match_number_tolerance():
    assert key_match("100.00", "100.005", Tol(type="number", abs=0.01)) is True
    assert key_match("100.00", "100.50", Tol(type="number", abs=0.01)) is False
    assert key_match("¥1,200.00", "1200", Tol(type="number", abs=0.0)) is True  # strip + parse


def test_key_match_date_days():
    assert key_match("2026-01-26", "2026-01-28", Tol(type="date_days", days=3)) is True
    assert key_match("2026-01-26", "2026-02-10", Tol(type="date_days", days=3)) is False


def test_key_match_absent():
    assert key_match(None, None, Tol(type="exact")) is True       # both absent → nothing contradicts
    assert key_match("x", "", Tol(type="exact")) is False          # one absent → mismatch
    assert key_match("", None, Tol(type="number", abs=1)) is True  # both absent


def test_key_match_unparseable_number_is_mismatch():
    assert key_match("abc", "100", Tol(type="number", abs=1)) is False


# --- judge_pair (L1 + L2 escalation) ----------------------------------------

async def test_judge_pair_all_match():
    maps = [_km("amount", "amount", Tol(type="number", abs=0.01)),
            _km("order_no", "ref_no", Tol(type="exact"))]
    v = await judge_pair(
        {"amount": "100.00", "order_no": "A1"}, {"amount": "100.00", "ref_no": "A1"},
        source="pay", mappings_for_source=maps, anchor_schema={}, source_schema={},
    )
    assert v.status == "match" and v.score == 1.0 and v.mismatched_fields == []


async def test_judge_pair_clean_no_match_skips_llm():
    maps = [_km("amount", "amount", Tol(type="number", abs=0.01)),
            _km("order_no", "ref_no", Tol(type="exact"))]
    called = {"n": 0}

    class _P:
        async def extract(self, **kw):
            called["n"] += 1
            return ProviderResult(raw_json={"match": True}, model_id="x")

    v = await judge_pair(
        {"amount": "1", "order_no": "A"}, {"amount": "999", "ref_no": "Z"},
        source="pay", mappings_for_source=maps, anchor_schema={}, source_schema={},
        provider=_P(),
    )
    assert v.status == "mismatch" and called["n"] == 0   # no keys agree → no LLM spend


async def test_judge_pair_partial_without_provider_stays_mismatch():
    maps = [_km("amount", "amount", Tol(type="number", abs=0.01)),
            _km("merchant", "merchant", Tol(type="exact"))]
    v = await judge_pair(
        {"amount": "100.00", "merchant": "海信"}, {"amount": "100.00", "merchant": "海信日本"},
        source="pay", mappings_for_source=maps, anchor_schema={}, source_schema={},
    )
    assert v.status == "mismatch" and "merchant" in v.mismatched_fields and v.score == 0.5


async def test_judge_pair_partial_escalates_to_llm():
    maps = [_km("amount", "amount", Tol(type="number", abs=0.01)),
            _km("merchant", "merchant", Tol(type="exact"))]

    class _P:
        async def extract(self, **kw):
            return ProviderResult(raw_json={"match": True, "reason": "same company"}, model_id="x")

    v = await judge_pair(
        {"amount": "100.00", "merchant": "海信"}, {"amount": "100.00", "merchant": "海信日本"},
        source="pay", mappings_for_source=maps, anchor_schema={}, source_schema={},
        provider=_P(), rules="商户名不同写法但同一公司视为一致",
    )
    assert v.status == "match" and v.reason == "same company"


async def test_judge_pair_no_mappings_is_mismatch():
    v = await judge_pair({}, {}, source="pay", mappings_for_source=[],
                         anchor_schema={}, source_schema={})
    assert v.status == "mismatch" and v.score == 0.0
