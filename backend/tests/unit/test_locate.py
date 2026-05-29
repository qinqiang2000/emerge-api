"""Tests for the field-source-grounding resolver (locate_fields).

Spans are injected by monkeypatching ``extract_textlayer`` + page count, so
these tests need no real PDF or LLM. Each "page" is a list of
``{bbox, text, font_size}`` span dicts (the textlayer shape).

Async bodies are driven via ``asyncio.run`` inside plain sync test functions so
the suite's pytest-asyncio configuration is irrelevant.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.schemas.schema_field import SchemaField
from app.tools import locate as locate_mod


# --- fixtures / helpers ----------------------------------------------------


def _span(text: str, bbox=(10.0, 20.0, 110.0, 32.0), size: float = 9.0) -> dict:
    return {"bbox": list(bbox), "text": text, "font_size": size}


class _FakePV:
    def __init__(self, fields):
        self.schema = fields


def _install(monkeypatch, *, fields, pages: dict[int, list[dict]]):
    """Wire up read_active_prompt, extract_textlayer, and page count via mocks.

    ``pages`` maps 1-based page number → list of span dicts.
    """
    import app.tools.prompt as prompt_mod

    async def fake_read_active_prompt(ws, pid):
        return _FakePV(fields)

    monkeypatch.setattr(prompt_mod, "read_active_prompt", fake_read_active_prompt)

    async def fake_textlayer(ws, pid, fname, *, page, skip_ocr=False):
        return {
            "page_w": 600.0,
            "page_h": 800.0,
            "image_w": 600,
            "image_h": 800,
            "scanned": False,
            "text_source": "textlayer",
            "spans": pages.get(page, []),
        }

    monkeypatch.setattr(locate_mod, "extract_textlayer", fake_textlayer)

    async def fake_page_count(ws, pid, fname):
        return max(pages) if pages else 0

    monkeypatch.setattr(locate_mod, "_page_count", fake_page_count)


def _run(entities, evidence, fields, pages, monkeypatch):
    _install(monkeypatch, fields=fields, pages=pages)
    return asyncio.run(
        locate_mod.locate_fields(
            Path("ws"), "proj", "doc.pdf", entities=entities, evidence=evidence
        )
    )


# --- tier 0: exact ---------------------------------------------------------


def test_tier0_exact(monkeypatch):
    fields = [SchemaField(name="vendor", type="string", description="v")]
    pages = {1: [_span("Acme Corporation")]}
    locs = _run(
        [{"vendor": "Acme Corporation"}],
        [{"vendor": {"page": 1, "source": None}}],
        fields,
        pages,
        monkeypatch,
    )
    assert len(locs) == 1
    assert locs[0].status == "exact"
    assert locs[0].page == 1
    assert locs[0].rects == [[10.0, 20.0, 110.0, 32.0]]


# --- tier 0: fuzzy ---------------------------------------------------------


def test_tier0_fuzzy(monkeypatch):
    fields = [SchemaField(name="vendor", type="string", description="v")]
    # span text close but not equal/substring → partial_ratio above threshold
    pages = {1: [_span("Acme Corporatlon Ltd")]}
    locs = _run(
        [{"vendor": "Acme Corporation"}],
        [{"vendor": {"page": 1, "source": None}}],
        fields,
        pages,
        monkeypatch,
    )
    assert locs[0].status == "fuzzy"
    assert locs[0].score >= 85.0
    assert locs[0].rects


# --- tier 1: normalized (type-aware) ---------------------------------------


def test_tier1_normalized_date(monkeypatch):
    fields = [
        SchemaField(name="invoice_date", type="string", format="date", description="d")
    ]
    pages = {1: [_span("15 Jan 2024")]}
    locs = _run(
        [{"invoice_date": "2024-01-15"}],
        [{"invoice_date": {"page": 1, "source": None}}],
        fields,
        pages,
        monkeypatch,
    )
    assert locs[0].status == "normalized"
    assert locs[0].page == 1
    assert locs[0].rects == [[10.0, 20.0, 110.0, 32.0]]


# --- tier 2: quote ---------------------------------------------------------


def test_tier2_quote(monkeypatch):
    # value is reformatted/derived and not literally on the page, but the
    # verbatim source quote is.
    fields = [SchemaField(name="total", type="string", description="t")]
    pages = {1: [_span("Balance due: 1.234,56 EUR")]}
    locs = _run(
        [{"total": "EUR 1234.56 (normalized)"}],
        [{"total": {"page": 1, "source": "Balance due: 1.234,56 EUR"}}],
        fields,
        pages,
        monkeypatch,
    )
    assert locs[0].status == "quote"
    assert locs[0].rects


# --- none fallback ---------------------------------------------------------


def test_none_when_not_found(monkeypatch):
    fields = [SchemaField(name="vendor", type="string", description="v")]
    pages = {1: [_span("Totally unrelated text")]}
    locs = _run(
        [{"vendor": "Acme Corporation"}],
        [{"vendor": {"page": 1, "source": None}}],
        fields,
        pages,
        monkeypatch,
    )
    assert locs[0].status == "none"
    assert locs[0].rects == []
    assert locs[0].page == 1  # page hint preserved on miss


# --- multi-span union ------------------------------------------------------


def test_multi_span_union(monkeypatch):
    fields = [SchemaField(name="addr", type="string", description="a")]
    # value substring-matches two spans (wrapped across lines)
    pages = {
        1: [
            _span("221B Baker", bbox=(10, 20, 80, 32)),
            _span("221B Baker", bbox=(10, 34, 80, 46)),
            _span("nothing here", bbox=(10, 60, 80, 72)),
        ]
    }
    locs = _run(
        [{"addr": "221B Baker"}],
        [{"addr": {"page": 1, "source": None}}],
        fields,
        pages,
        monkeypatch,
    )
    assert locs[0].status == "exact"
    assert len(locs[0].rects) == 2


# --- page-hint priority vs full-doc fallback -------------------------------


def test_evidence_page_priority(monkeypatch):
    fields = [SchemaField(name="vendor", type="string", description="v")]
    # same text on page 1 and page 2; hint says page 2 → must report page 2
    pages = {
        1: [_span("Acme Corporation", bbox=(1, 1, 2, 2))],
        2: [_span("Acme Corporation", bbox=(5, 5, 6, 6))],
    }
    locs = _run(
        [{"vendor": "Acme Corporation"}],
        [{"vendor": {"page": 2, "source": None}}],
        fields,
        pages,
        monkeypatch,
    )
    assert locs[0].page == 2
    assert locs[0].rects == [[5.0, 5.0, 6.0, 6.0]]


def test_full_doc_fallback_when_hint_misses(monkeypatch):
    fields = [SchemaField(name="vendor", type="string", description="v")]
    # hint page (1) lacks the value; it's on page 3 → fallback finds it
    pages = {
        1: [_span("cover sheet")],
        2: [_span("table of contents")],
        3: [_span("Acme Corporation", bbox=(9, 9, 9, 9))],
    }
    locs = _run(
        [{"vendor": "Acme Corporation"}],
        [{"vendor": {"page": 1, "source": None}}],
        fields,
        pages,
        monkeypatch,
    )
    assert locs[0].status == "exact"
    assert locs[0].page == 3


# --- derived field (no literal source) -------------------------------------


def test_derived_field_none(monkeypatch):
    fields = [SchemaField(name="line_total", type="string", description="lt")]
    pages = {1: [_span("Qty 3 @ 4.00")]}
    # derived value, page null, no source → none
    locs = _run(
        [{"line_total": "ZZZ-derived-no-anchor"}],
        [{"line_total": {"page": None, "source": None}}],
        fields,
        pages,
        monkeypatch,
    )
    assert locs[0].status == "none"
    assert locs[0].rects == []


# --- legacy int evidence shape still works ---------------------------------


def test_legacy_int_evidence(monkeypatch):
    fields = [SchemaField(name="vendor", type="string", description="v")]
    pages = {1: [_span("Acme Corporation")]}
    locs = _run(
        [{"vendor": "Acme Corporation"}],
        [{"vendor": 1}],  # legacy {field: int}
        fields,
        pages,
        monkeypatch,
    )
    assert locs[0].status == "exact"
    assert locs[0].page == 1


# --- evidence=None does not crash ------------------------------------------


def test_evidence_none(monkeypatch):
    fields = [SchemaField(name="vendor", type="string", description="v")]
    pages = {1: [_span("Acme Corporation")]}
    locs = _run(
        [{"vendor": "Acme Corporation"}],
        None,
        fields,
        pages,
        monkeypatch,
    )
    # no page hint → full-doc scan still finds it
    assert locs[0].status == "exact"
    assert locs[0].page == 1
