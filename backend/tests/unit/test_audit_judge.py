"""Audit judge — NL rules over document images, one trip, index-aligned
(app/match/audit.py)."""
from __future__ import annotations

from app.match.audit import audit_group
from app.provider.base import ImageBlock, ProviderResult, TextBlock


class _MockProvider:
    """Returns a fixed `checks` array; optionally records the user_content it
    received (to assert image attachment / fields hint)."""

    def __init__(self, checks=None, capture=None, raise_exc=False):
        self._checks = checks if checks is not None else []
        self._capture = capture
        self._raise = raise_exc

    async def extract(self, *, model_id, system_prompt, user_content, response_schema, params=None):
        if self._capture is not None:
            self._capture["user_content"] = user_content
        if self._raise:
            raise RuntimeError("boom")
        return ProviderResult(raw_json={"checks": self._checks}, model_id=model_id)


def _img(tag="c3R1Yg=="):
    return ImageBlock(media_type="image/png", data_b64=tag)


_RULES = ["甲方为环胜", "乙方盖红章", "金额一致"]
_DOCS = {"quote": [_img()], "receipt": [_img()]}


async def test_aligned_verdicts():
    p = _MockProvider(checks=[
        {"index": 0, "status": "pass", "reason": "甲方=环胜"},
        {"index": 1, "status": "fail", "reason": "无红章"},
        {"index": 2, "status": "pass", "reason": "金额一致"},
    ])
    out = await audit_group(doc_images=_DOCS, audit_rules=_RULES, provider=p)
    assert [c.status for c in out] == ["pass", "fail", "pass"]
    assert [c.rule for c in out] == _RULES


async def test_missing_index_becomes_unclear():
    p = _MockProvider(checks=[
        {"index": 0, "status": "pass", "reason": "ok"},
        {"index": 2, "status": "pass", "reason": "ok"},
    ])
    out = await audit_group(doc_images=_DOCS, audit_rules=_RULES, provider=p)
    assert out[0].status == "pass"
    assert out[1].status == "unclear"   # missing → unclear, never coerced to fail
    assert out[2].status == "pass"


async def test_out_of_order_and_bad_status():
    p = _MockProvider(checks=[
        {"index": 2, "status": "pass", "reason": "z"},
        {"index": 0, "status": "weird", "reason": "x"},   # invalid status → unclear
        {"index": 1, "status": "fail", "reason": "y"},
    ])
    out = await audit_group(doc_images=_DOCS, audit_rules=_RULES, provider=p)
    assert out[0].status == "unclear" and out[1].status == "fail" and out[2].status == "pass"


async def test_no_provider_all_unclear():
    out = await audit_group(doc_images=_DOCS, audit_rules=_RULES, provider=None)
    assert all(c.status == "unclear" for c in out) and len(out) == 3


async def test_provider_failure_all_unclear():
    p = _MockProvider(raise_exc=True)
    out = await audit_group(doc_images=_DOCS, audit_rules=_RULES, provider=p)
    assert all(c.status == "unclear" for c in out)


async def test_empty_rules_returns_empty():
    out = await audit_group(doc_images=_DOCS, audit_rules=[], provider=_MockProvider())
    assert out == []


async def test_documents_sent_as_images():
    cap: dict = {}
    p = _MockProvider(checks=[{"index": 0, "status": "pass", "reason": "ok"}], capture=cap)
    await audit_group(doc_images=_DOCS, audit_rules=["乙方盖红章"], provider=p)
    blocks = cap["user_content"]
    # both docs' images are present (source of truth) + at least one text block
    assert sum(isinstance(b, ImageBlock) for b in blocks) == 2
    assert any(isinstance(b, TextBlock) for b in blocks)


async def test_fields_hint_included_when_provided():
    cap: dict = {}
    p = _MockProvider(checks=[{"index": 0, "status": "pass", "reason": "ok"}], capture=cap)
    await audit_group(
        doc_images=_DOCS, audit_rules=["金额一致"],
        doc_fields={"quote": {"金额": "370815.56"}}, provider=p,
    )
    texts = "".join(b.text for b in cap["user_content"] if isinstance(b, TextBlock))
    assert "370815.56" in texts and "reference only" in texts   # hint, not source of truth


# --- B1: evidence citations -----------------------------------------------------


async def test_evidence_backfilled_and_missing_defaults_empty():
    p = _MockProvider(checks=[
        {"index": 0, "status": "pass", "reason": "甲方=环胜",
         "evidence": [{"doc": "quote", "page": 1, "quote": "甲方：环胜电子商务"}]},
        {"index": 1, "status": "fail", "reason": "无红章"},   # no evidence key → []
        {"index": 2, "status": "pass", "reason": "金额一致",
         "evidence": [{"doc": "quote", "quote": "¥370,815.56"},
                      {"doc": "receipt", "page": 3, "quote": "370815.56"}]},
    ])
    out = await audit_group(doc_images=_DOCS, audit_rules=_RULES, provider=p)
    assert [len(c.evidence) for c in out] == [1, 0, 2]
    ev = out[0].evidence[0]
    assert (ev.doc, ev.page, ev.quote) == ("quote", 1, "甲方：环胜电子商务")
    assert out[2].evidence[0].page is None      # page optional
    assert out[2].evidence[1].doc == "receipt" and out[2].evidence[1].page == 3


async def test_malformed_evidence_entries_dropped_never_fail():
    p = _MockProvider(checks=[
        {"index": 0, "status": "pass", "reason": "ok",
         "evidence": [
             {"doc": "quote"},                        # missing quote → dropped
             {"page": 2, "quote": "无doc"},            # missing doc → dropped
             "not-a-dict",                             # → dropped
             {"doc": "receipt", "quote": "金额 100"},   # valid → kept
         ]},
        {"index": 1, "status": "pass", "reason": "ok", "evidence": "garbage"},  # non-list → []
        {"index": 2, "status": "pass", "reason": "ok", "evidence": None},       # null → []
    ])
    out = await audit_group(doc_images=_DOCS, audit_rules=_RULES, provider=p)
    assert [(e.doc, e.quote) for e in out[0].evidence] == [("receipt", "金额 100")]
    assert out[1].evidence == [] and out[2].evidence == []
    # the malformed evidence never poisoned the verdicts themselves
    assert [c.status for c in out] == ["pass", "pass", "pass"]


async def test_overlong_quote_truncated_defensively():
    p = _MockProvider(checks=[
        {"index": 0, "status": "pass", "reason": "ok",
         "evidence": [{"doc": "quote", "quote": "甲" * 300}]},
        {"index": 1, "status": "pass", "reason": "ok"},
        {"index": 2, "status": "pass", "reason": "ok"},
    ])
    out = await audit_group(doc_images=_DOCS, audit_rules=_RULES, provider=p)
    assert out[0].evidence[0].quote == "甲" * 200   # cap at 200, entry kept


async def test_fields_optional():
    # audit works with images and NO extracted fields (extraction not required)
    cap: dict = {}
    p = _MockProvider(checks=[{"index": 0, "status": "pass", "reason": "ok"}], capture=cap)
    out = await audit_group(doc_images=_DOCS, audit_rules=["甲方为环胜"], doc_fields=None, provider=p)
    assert out[0].status == "pass"
    texts = "".join(b.text for b in cap["user_content"] if isinstance(b, TextBlock))
    assert "Pre-extracted fields" not in texts
