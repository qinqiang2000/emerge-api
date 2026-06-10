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


async def test_fields_optional():
    # audit works with images and NO extracted fields (extraction not required)
    cap: dict = {}
    p = _MockProvider(checks=[{"index": 0, "status": "pass", "reason": "ok"}], capture=cap)
    out = await audit_group(doc_images=_DOCS, audit_rules=["甲方为环胜"], doc_fields=None, provider=p)
    assert out[0].status == "pass"
    texts = "".join(b.text for b in cap["user_content"] if isinstance(b, TextBlock))
    assert "Pre-extracted fields" not in texts
