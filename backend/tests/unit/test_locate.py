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
    assert locs[0].score > 0.0
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


# --- numeric fields: token compare, never digit-run substring --------------


def test_numeric_no_substring_false_positive(monkeypatch):
    """A short numeric value must not match a longer digit run that merely
    contains its digits (the ABA-routing-number bug: 111 ⊄ 111000012)."""
    fields = [SchemaField(name="amt", type="number", description="a")]
    pages = {
        1: [
            _span("ABA #: 111000012", bbox=(10, 300, 300, 312)),
            _span("111.00 USD", bbox=(10, 20, 110, 32)),
        ]
    }
    locs = _run(
        [{"amt": 111}],
        [{"amt": {"page": 1, "source": None}}],
        fields,
        pages,
        monkeypatch,
    )
    assert locs[0].status in ("exact", "normalized")
    assert locs[0].page == 1
    # only the real 111.00 amount, never the ABA digit run
    assert locs[0].rects == [[10.0, 20.0, 110.0, 32.0]]


def test_numeric_multi_occurrence_is_ambiguous_none(monkeypatch):
    """The same amount scattered across the page (unit price, line total,
    grand total) can't be disambiguated by value alone → none, not a shotgun
    of every 111 on the page."""
    fields = [SchemaField(name="amt", type="number", description="a")]
    pages = {
        1: [
            _span("111.00 USD", bbox=(10, 20, 110, 32)),
            _span("111.00 USD", bbox=(10, 200, 110, 212)),
            _span("EA 111.00 USD 111.00 USD", bbox=(10, 400, 300, 412)),
        ]
    }
    locs = _run(
        [{"amt": 111}],
        [{"amt": {"page": 1, "source": None}}],
        fields,
        pages,
        monkeypatch,
    )
    assert locs[0].status == "none"
    assert locs[0].rects == []


def test_zero_value_excludes_digit_runs(monkeypatch):
    """value 0 must match only a numeric token equal to 0, never every span
    that happens to contain the digit '0'."""
    fields = [SchemaField(name="tax", type="number", description="t")]
    pages = {
        1: [
            _span("Chicago IL 60674-8571", bbox=(10, 300, 300, 312)),
            _span("Acct 740008571", bbox=(10, 330, 300, 342)),
            _span("0.00 USD", bbox=(10, 20, 110, 32)),
        ]
    }
    locs = _run(
        [{"tax": 0}],
        [{"tax": {"page": 1, "source": None}}],
        fields,
        pages,
        monkeypatch,
    )
    assert locs[0].status in ("exact", "normalized")
    assert locs[0].rects == [[10.0, 20.0, 110.0, 32.0]]


def test_source_quote_disambiguates_repeated_value(monkeypatch):
    """When the value repeats, the model's verbatim source quote is the anchor:
    quote 'Total 111.00 USD' pins the grand-total line, ignoring the line-item
    and bare-amount occurrences."""
    fields = [SchemaField(name="amt", type="number", description="a")]
    pages = {
        1: [
            _span("EA 111.00 USD 111.00 USD", bbox=(10, 90, 300, 102)),
            _span("111.00 USD", bbox=(500, 90, 600, 102)),
            _span("Total 111.00 USD", bbox=(10, 690, 300, 702)),
        ]
    }
    locs = _run(
        [{"amt": 111}],
        [{"amt": {"page": 1, "source": "Total 111.00 USD"}}],
        fields,
        pages,
        monkeypatch,
    )
    assert locs[0].status == "quote"
    assert locs[0].rects == [[10.0, 690.0, 300.0, 702.0]]


def test_exact_value_beats_quote(monkeypatch):
    """A literal full-value match is the most trustworthy anchor: when the value
    has its own clean span it wins over the (label+value) quote, boxing just the
    value — not the longer label span the old quote-first path picked."""
    fields = [SchemaField(name="po", type="string", description="po")]
    pages = {
        1: [
            _span("Your P.O.:", bbox=(10, 100, 110, 112)),   # label column
            _span("108575201", bbox=(300, 100, 400, 112)),   # value column, same line
            _span("RAN:", bbox=(10, 130, 110, 142)),         # next line, no match
        ]
    }
    locs = _run(
        [{"po": "108575201"}],
        [{"po": {"page": 1, "source": "Your P.O.: 108575201"}}],
        fields,
        pages,
        monkeypatch,
    )
    assert locs[0].status == "exact"
    assert locs[0].rects == [[300, 100, 400, 112]]  # the value, not the label


def test_exact_value_beats_wrong_logo_quote(monkeypatch):
    """The model sometimes points the quote at a logo/letterhead ("AIRBUS") while
    the real value text sits in the body. A full-span-equal value match must win
    over the short wrong quote, so the box lands on the company line, not the
    logo."""
    fields = [SchemaField(name="billFromName", type="string", description="seller")]
    val = "Airbus Americas Customer Services, Inc."
    pages = {
        1: [
            _span("AIRBUS", bbox=(275, 34, 362, 51)),        # logo (the bad quote)
            _span(val, bbox=(425, 745, 535, 754)),           # the real company line
        ]
    }
    locs = _run(
        [{"billFromName": val}],
        [{"billFromName": {"page": 1, "source": "AIRBUS"}}],
        fields,
        pages,
        monkeypatch,
    )
    assert locs[0].status == "exact"
    assert locs[0].rects == [[425, 745, 535, 754]]  # company line, not the logo


def test_ordinal_tiebreak_twin_totals(monkeypatch):
    """Two fields share one identical quote ("Total 111.00 USD" — net == grand
    because tax is 0) that matches exactly two equally-good lines. Neither value
    nor quote can split them, so the ordinal tie-break assigns them by reading
    order: the first (schema-order) field → the top line, the second → below."""
    fields = [
        SchemaField(name="totalNetAmount", type="number", description="net"),
        SchemaField(name="totalAmount", type="number", description="grand"),
    ]
    pages = {
        1: [
            _span("Total", bbox=(10, 400, 60, 412)),
            _span("111.00 USD", bbox=(300, 400, 400, 412)),   # top line (net)
            _span("Total", bbox=(10, 690, 60, 702)),
            _span("111.00 USD", bbox=(300, 690, 400, 702)),   # bottom line (grand)
        ]
    }
    locs = _run(
        [{"totalNetAmount": 111, "totalAmount": 111}],
        [{"totalNetAmount": {"page": 1, "source": "Total 111.00 USD"},
          "totalAmount": {"page": 1, "source": "Total 111.00 USD"}}],
        fields,
        pages,
        monkeypatch,
    )
    by = {l.path: l for l in locs}
    assert by["totalNetAmount"].status == "quote"
    assert by["totalAmount"].status == "quote"
    # net → top line, grand → bottom line (reading order)
    assert min(r[1] for r in by["totalNetAmount"].rects) == 400
    assert min(r[1] for r in by["totalAmount"].rects) == 690


def test_ordinal_tiebreak_only_groups_siblings(monkeypatch):
    """The ordinal tie-break must group fields by (parent, quote) — siblings only.

    Regression: grounding gave a top-level ``currency`` the bogus quote
    "111.00 USD" that the line-item ``netAmount`` / ``grossAmount`` legitimately
    carry. Grouped by quote alone, that made 3 fields ⇄ 3 equally-good lines
    (the line-item row + two grand-total lines) — a false K⇄K tie that assigned
    the line-item amounts to the document's grand totals. Sibling-scoping splits
    the group, so the array amounts no longer reach a tie and fall back to none
    rather than lighting up the wrong (grand-total) line."""
    fields = [
        SchemaField(name="currency", type="string", description="ccy"),
        SchemaField(
            name="lines",
            type="array",
            description="line items",
            items=SchemaField(
                type="object",
                description="row",
                properties=[
                    SchemaField(name="netAmount", type="number", description="net"),
                    SchemaField(name="grossAmount", type="number", description="gross"),
                ],
            ),
        ),
    ]
    pages = {
        1: [
            # line-item row: unit-price + total-price both "111.00 USD" (one line)
            _span("111.00 USD", bbox=(300, 90, 400, 102)),
            _span("111.00 USD", bbox=(450, 90, 550, 102)),
            # two grand-total lines further down
            _span("111.00 USD", bbox=(300, 600, 400, 612)),
            _span("111.00 USD", bbox=(300, 690, 400, 702)),
        ]
    }
    locs = _run(
        [{"currency": "111.00 USD", "lines": [{"netAmount": 111, "grossAmount": 111}]}],
        [{
            "currency": {"page": 1, "source": "111.00 USD"},
            "lines[].netAmount": {"page": 1, "source": "111.00 USD"},
            "lines[].grossAmount": {"page": 1, "source": "111.00 USD"},
        }],
        fields,
        pages,
        monkeypatch,
    )
    by = {l.path: l for l in locs}
    # Ambiguous ("111.00 USD" repeats 4× with no disambiguating anchor) → none,
    # never a confident assignment to a grand-total line.
    assert by["lines[].netAmount"].status == "none"
    assert by["lines[].grossAmount"].status == "none"


def test_quote_coverage_is_union_not_sum(monkeypatch):
    """A line-item row carries the value twice (net + gross both '111.00 USD').
    Summed coverage would let it (2×) beat the real 'Total 111.00 USD' line; the
    set-union coverage must count the repeated quote region once, so the labelled
    Total line wins."""
    fields = [SchemaField(name="amt", type="number", description="a")]
    pages = {
        1: [
            _span("111.00 USD", bbox=(300, 90, 400, 102)),   # line-item net
            _span("111.00 USD", bbox=(450, 90, 550, 102)),   # line-item gross (same line)
            _span("Total", bbox=(10, 690, 60, 702)),         # grand-total label
            _span("111.00 USD", bbox=(300, 690, 400, 702)),  # grand-total value (same line)
        ]
    }
    locs = _run(
        [{"amt": 111}],
        [{"amt": {"page": 1, "source": "Total 111.00 USD"}}],
        fields,
        pages,
        monkeypatch,
    )
    assert locs[0].status == "quote"
    assert sorted(locs[0].rects) == sorted([[10, 690, 60, 702], [300, 690, 400, 702]])


def test_quote_repeated_identical_line_is_ambiguous_none(monkeypatch):
    """Two lines that cover the quote identically (net total == grand total, both
    'Total 111.00 USD') are genuinely ambiguous → none (page-level fallback),
    never a confident wrong pick."""
    fields = [SchemaField(name="amt", type="number", description="a")]
    pages = {
        1: [
            _span("Total", bbox=(10, 400, 60, 412)),
            _span("111.00 USD", bbox=(300, 400, 400, 412)),
            _span("Total", bbox=(10, 690, 60, 702)),
            _span("111.00 USD", bbox=(300, 690, 400, 702)),
        ]
    }
    locs = _run(
        [{"amt": 111}],
        [{"amt": {"page": 1, "source": "Total 111.00 USD"}}],
        fields,
        pages,
        monkeypatch,
    )
    assert locs[0].status == "none"
    assert locs[0].rects == []


def test_quote_no_fuzzy_cross_contamination(monkeypatch):
    """'0.00 USD' must NOT match the quote 'Total 111.00 USD' (the old fuzzy
    partial-ratio branch scored it ~0.84 and lit up the Sales-Tax line)."""
    fields = [SchemaField(name="amt", type="number", description="a")]
    pages = {1: [_span("0.00 USD", bbox=(300, 500, 400, 512))]}
    locs = _run(
        [{"amt": 111}],
        [{"amt": {"page": 1, "source": "Total 111.00 USD"}}],
        fields,
        pages,
        monkeypatch,
    )
    assert locs[0].status == "none"


def test_distinctive_string_repeat_unions(monkeypatch):
    """A long distinctive string matched exactly in several places (invoice
    number in header + payment stub) is the same entity → highlight all, unlike
    a numeric collision."""
    fields = [SchemaField(name="invoiceNumber", type="string", description="n")]
    pages = {
        1: [
            _span("74671636", bbox=(400, 40, 500, 52)),
            _span("unrelated", bbox=(10, 200, 110, 212)),
            _span("74671636", bbox=(50, 700, 150, 712)),
        ]
    }
    locs = _run(
        [{"invoiceNumber": "74671636"}],
        [{"invoiceNumber": {"page": 1, "source": None}}],
        fields,
        pages,
        monkeypatch,
    )
    assert locs[0].status == "exact"
    assert len(locs[0].rects) == 2  # both occurrences, not the unrelated span


def test_unannotated_date_string_matches(monkeypatch):
    """invoiceDate declared as plain `string` (no format=date) still matches a
    differently-formatted date on the page via the heuristic."""
    fields = [SchemaField(name="invoiceDate", type="string", description="d")]
    pages = {1: [_span("March 20, 2024", bbox=(400, 600, 520, 612))]}
    locs = _run(
        [{"invoiceDate": "2024-03-20"}],
        [{"invoiceDate": {"page": 1, "source": None}}],
        fields,
        pages,
        monkeypatch,
    )
    assert locs[0].status == "normalized"
    assert locs[0].rects == [[400.0, 600.0, 520.0, 612.0]]


def test_short_string_substring_respects_word_boundary(monkeypatch):
    """A short string value must match on token boundaries, not mid-word
    (e.g. 'Air' must not light up 'Airbus')."""
    fields = [SchemaField(name="code", type="string", description="c")]
    pages = {1: [_span("Airbus Americas")]}
    locs = _run(
        [{"code": "Air"}],
        [{"code": {"page": 1, "source": None}}],
        fields,
        pages,
        monkeypatch,
    )
    assert locs[0].status == "none"
    assert locs[0].rects == []
