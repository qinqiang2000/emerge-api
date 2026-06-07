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


def test_page_hint_is_authoritative_no_cross_page_drift(monkeypatch):
    """A present page hint is authoritative: locate must NOT relocate the field
    onto another page even when the value sits there. In a multi-invoice doc the
    seller boilerplate is byte-identical on every invoice, so a whole-doc scan
    would teleport the highlight to another invoice's copy (the p17→p5 drift).
    Hint says page 1 (which lacks the value here) → stay none on page 1, never
    jump to the page-3 lookalike."""
    fields = [SchemaField(name="vendor", type="string", description="v")]
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
    assert locs[0].status == "none"
    assert locs[0].page == 1  # hint preserved; no drift to page 3
    assert locs[0].rects == []


def test_full_doc_scan_when_no_page_hint(monkeypatch):
    """With NO page hint (legacy / derived evidence), the whole-doc scan still
    runs and finds the value wherever it uniquely sits."""
    fields = [SchemaField(name="vendor", type="string", description="v")]
    pages = {
        1: [_span("cover sheet")],
        2: [_span("table of contents")],
        3: [_span("Acme Corporation", bbox=(9, 9, 9, 9))],
    }
    locs = _run(
        [{"vendor": "Acme Corporation"}],
        [{"vendor": {"page": None, "source": None}}],
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


def test_numeric_value_matches_digit_spaced_amount(monkeypatch):
    """CJK / boxed-grid invoices letter-space the digits of one amount: the value
    18668 must match a span printed as '¥ 1 8 , 6 6 8' (every digit spaced) and as
    '18, 668' (space after the thousands comma). Without the spaced-token pass the
    strict tokenizer split these into ['1','8',...] / ['18','668'] and the value
    lost its own literal anchor, silently degrading to quote-only. (The Yamato
    invoice totalAmount case.)"""
    fields = [SchemaField(name="totalAmount", type="number", description="t")]
    pages = {
        1: [
            _span("¥ 1 8 , 6 6 8", bbox=(300, 100, 460, 118)),
            _span("billed to ACME", bbox=(10, 300, 300, 312)),
        ]
    }
    locs = _run(
        [{"totalAmount": 18668}],
        [{"totalAmount": {"page": 1, "source": "¥ 1 8 , 6 6 8"}}],
        fields,
        pages,
        monkeypatch,
    )
    assert locs[0].status in ("exact", "normalized")
    assert locs[0].rects == [[300.0, 100.0, 460.0, 118.0]]


def test_numeric_value_matches_trailing_zero_decimal(monkeypatch):
    """Decimal trailing-zero precision must not block the value anchor: value
    123.0 matches a span printed '123.0000' (Decimal-numeric equality, not
    surface string)."""
    fields = [SchemaField(name="unitPrice", type="number", description="p")]
    pages = {1: [_span("123.0000", bbox=(300, 100, 360, 112))]}
    locs = _run(
        [{"unitPrice": 123.0}],
        [{"unitPrice": {"page": 1, "source": "123.0000"}}],
        fields,
        pages,
        monkeypatch,
    )
    assert locs[0].status in ("exact", "normalized")
    assert locs[0].rects == [[300.0, 100.0, 360.0, 112.0]]


def test_numeric_tokens_fold_only_unambiguous_spacing():
    """_numeric_tokens folds intra-number spacing — letter-spaced digits
    ('¥ 1 8 , 6 6 8') and a separator-hugging space ('18, 668') — but never
    fuses two adjacent numbers. The bare multi-digit-group cases below are the
    regression that scattered / stole amount highlights on otherwise-OK
    invoices, so they must NOT produce the fused value while the real groups are
    still recovered by the strict pass."""
    from decimal import Decimal

    def nt(s: str) -> list:
        return locate_mod._numeric_tokens(locate_mod._nfkc(s))

    # intended folds (one number, intra-number spacing)
    assert Decimal("18668") in nt("¥ 1 8 , 6 6 8")
    assert Decimal("18668") in nt("18, 668")
    # ambiguous adjacencies — two numbers, a qty+price, a split date — never fuse
    assert Decimal("18668") not in nt("18 668")
    assert Decimal("21500.00") not in nt("2 1,500.00")
    assert Decimal("20241231") not in nt("2024 12 31")
    assert Decimal("1234567") not in nt("No. 1 234567")
    # the real groups are still there (strict pass keeps each apart)
    assert Decimal("668") in nt("18 668")
    assert Decimal("1500.00") in nt("2 1,500.00")


def test_spaced_fusion_does_not_steal_repeated_amount(monkeypatch):
    """Regression guard for OK amount fields: the page carries the real total
    'Total 21,500.00' and a line item '2 1,500.00' (qty 2 × unit 1,500). The old
    spaced pass fused '2 1,500.00' → 21500.00, so the value 21,500 matched TWO
    spans → ambiguous → none, silently breaking a field that used to land. With
    folding gated to unambiguous spacing, only the real total matches → one
    confident rect, and the line item keeps its own 1,500 group."""
    fields = [SchemaField(name="grandTotal", type="number", description="g")]
    pages = {
        1: [
            _span("Total 21,500.00", bbox=(300, 100, 460, 118)),
            _span("2 1,500.00", bbox=(300, 400, 460, 418)),
        ]
    }
    locs = _run(
        [{"grandTotal": 21500.00}],
        [{"grandTotal": {"page": 1, "source": None}}],
        fields,
        pages,
        monkeypatch,
    )
    assert locs[0].status in ("exact", "normalized")
    assert locs[0].rects == [[300.0, 100.0, 460.0, 118.0]]


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


def test_corroborated_quote_beats_offline_value_duplicate(monkeypatch):
    """A repeated value whose source quote names the RIGHT line must land there,
    not on a full-span duplicate elsewhere.

    The #14 KB060162 bug: the invoice number sits full-span (score 1.0) in a
    D/O-No. cell *and* as a substring (0.9) inside the quoted "NO: KB060162"
    header. Value-first alone picks the bare cell (1.0 > 0.9) and the highlight
    teleports to the wrong row. Because the quote literally CONTAINS the value and
    resolves to a DIFFERENT line than the value-first hit, the quote anchor wins —
    boxing the header line. (Contrast test_exact_value_beats_quote, where the
    value-first hit sits ON the quote line → overlap → value-first kept; and
    test_exact_value_beats_wrong_logo_quote, where the quote does NOT contain the
    value → value-first kept.)"""
    fields = [SchemaField(name="invoiceNumber", type="string", description="n")]
    pages = {
        1: [
            _span("NO: KB060162", bbox=(300, 40, 460, 52)),     # invoice header line
            _span("KB060162", bbox=(240, 320, 300, 334)),        # D/O-No. cell (duplicate)
        ]
    }
    locs = _run(
        [{"invoiceNumber": "KB060162"}],
        [{"invoiceNumber": {"page": 1, "source": "NO: KB060162"}}],
        fields,
        pages,
        monkeypatch,
    )
    assert locs[0].status == "quote"
    assert locs[0].page == 1
    assert locs[0].rects == [[300, 40, 460, 52]]  # header line, not the D/O cell


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
    # Ambiguous ("111.00 USD" repeats 4× with no disambiguating row sibling) →
    # none, never a confident assignment to a grand-total line. (currency is a
    # different parent, so it never pollutes the line-item amounts' tie-break.)
    assert by["lines[0].netAmount"].status == "none"
    assert by["lines[0].grossAmount"].status == "none"


def test_dedupe_aggregate_rect_dropped():
    """A wide line-level rect that encloses >=2 narrower word rects (fitz line
    span layered over OCR word spans) is dropped so the highlight paints tight
    word rings, not a wide ring over two narrow ones."""
    wide = [101.0, 412.0, 179.0, 425.0]   # "SHIM     SHIM" fitz line
    w1 = [100.0, 414.0, 125.0, 422.0]      # "SHIM" OCR word
    w2 = [161.0, 414.0, 186.0, 422.0]      # "SHIM" OCR word
    out = locate_mod._dedupe_aggregate_rects([wide, w1, w2])
    assert wide not in out
    assert sorted(out) == sorted([w1, w2])
    # a lone rect, or non-enclosing rects, pass through untouched
    assert locate_mod._dedupe_aggregate_rects([w1]) == [w1]
    assert sorted(locate_mod._dedupe_aggregate_rects([w1, w2])) == sorted([w1, w2])


def test_row_anchor_lineitem_amount(monkeypatch):
    """An array-child amount that repeats (row price + grand total) ties to none
    on its own, but its resolved row sibling (articleName) pins the row band, so
    the amount is anchored to its row line rather than the far-below grand total."""
    fields = [
        SchemaField(
            name="lines",
            type="array",
            description="line items",
            items=SchemaField(
                type="object",
                description="row",
                properties=[
                    SchemaField(name="articleName", type="string", description="name"),
                    SchemaField(name="netAmount", type="number", description="net"),
                ],
            ),
        ),
    ]
    pages = {
        1: [
            # line-item row (y≈100): distinctive name + the row's amount
            _span("WIDGET ABC", bbox=(100, 100, 200, 112)),
            _span("111.00 USD", bbox=(400, 100, 500, 112)),
            # document grand total far below (y≈400): same amount, no anchor
            _span("Total", bbox=(10, 400, 60, 412)),
            _span("111.00 USD", bbox=(400, 400, 500, 412)),
        ]
    }
    locs = _run(
        [{"lines": [{"articleName": "WIDGET ABC", "netAmount": 111}]}],
        [{
            "lines[].articleName": {"page": 1, "source": "WIDGET ABC"},
            "lines[].netAmount": {"page": 1, "source": "111.00 USD"},
        }],
        fields,
        pages,
        monkeypatch,
    )
    by = {l.path: l for l in locs}
    amt = by["lines[0].netAmount"]
    assert amt.status == "quote"
    # anchored to the row line (y≈100), never the grand-total line (y≈400)
    assert all(r[1] < 200 for r in amt.rects)
    assert amt.rects == [[400, 100, 500, 112]]


def test_array_child_value_overrides_misgrounded_quote(monkeypatch):
    """A single-row array child surfaces its value so a wrong source quote can't
    drag the highlight to the wrong cell.

    items[].item = "房费" but grounding mis-pointed its source at "支付宝" (an
    adjacent row). Flying blind on the quote lit 支付宝; surfacing the value lets
    the exact full-value match win and land on the real 房费 cell."""
    fields = [
        SchemaField(
            name="items",
            type="array",
            description="line items",
            items=SchemaField(
                type="object",
                description="row",
                properties=[SchemaField(name="item", type="string", description="name")],
            ),
        ),
    ]
    pages = {
        1: [
            _span("房费", bbox=(150, 1084, 188, 1104)),
            _span("支付宝", bbox=(150, 1119, 188, 1139)),
        ]
    }
    locs = _run(
        [{"items": [{"item": "房费"}]}],
        [{"items[].item": {"page": 1, "source": "支付宝"}}],  # mis-grounded
        fields,
        pages,
        monkeypatch,
    )
    by = {l.path: l for l in locs}
    item = by["items[0].item"]
    assert item.status == "exact"
    assert item.rects == [[150, 1084, 188, 1104]]  # 房费, not 支付宝


def test_array_child_per_row_distinct_values_resolve(monkeypatch):
    """Per-row expansion: each row's child resolves to its OWN cell by value, even
    when the rows carry different values. A collapsed `items[].item` slot used to
    share one highlight across rows; concrete `items[0].item` / `items[1].item`
    paths let row 0 ("apple") and row 1 ("banana") each light their own line."""
    fields = [
        SchemaField(
            name="items",
            type="array",
            description="line items",
            items=SchemaField(
                type="object",
                description="row",
                properties=[SchemaField(name="item", type="string", description="name")],
            ),
        ),
    ]
    pages = {
        1: [
            _span("apple", bbox=(150, 100, 200, 112)),
            _span("banana", bbox=(150, 130, 200, 142)),
        ]
    }
    locs = _run(
        [{"items": [{"item": "apple"}, {"item": "banana"}]}],
        [{"items[].item": {"page": 1, "source": None}}],
        fields,
        pages,
        monkeypatch,
    )
    by = {l.path: l for l in locs}
    assert by["items[0].item"].status == "exact"
    assert by["items[0].item"].rects == [[150, 100, 200, 112]]   # apple
    assert by["items[1].item"].status == "exact"
    assert by["items[1].item"].rects == [[150, 130, 200, 142]]   # banana


def test_array_child_per_row_quote_resolves_each_row(monkeypatch):
    """Fix RC-A: each row's child must use its OWN source quote, keyed by the
    CONCRETE row path (`lines[0].unitPrice`, `lines[1].unitPrice`).

    The values repeat (both rows are 111) so value alone is ambiguous → the quote
    is the disambiguator. With the old collapsed `lines[].unitPrice` key (one
    last-row-wins quote shared by every row) BOTH rows landed on row 1's line.
    With per-row concrete-key evidence, row 0 → its line, row 1 → its line."""
    fields = [
        SchemaField(
            name="lines", type="array", description="rows",
            items=SchemaField(
                type="object", description="row",
                properties=[SchemaField(name="unitPrice", type="number", description="p")],
            ),
        ),
    ]
    pages = {
        1: [
            _span("Row A 111.00 USD", bbox=(100, 100, 400, 112)),
            _span("Row B 111.00 USD", bbox=(100, 200, 400, 212)),
        ]
    }
    locs = _run(
        [{"lines": [{"unitPrice": 111}, {"unitPrice": 111}]}],
        [{
            "lines[0].unitPrice": {"page": 1, "source": "Row A 111.00 USD"},
            "lines[1].unitPrice": {"page": 1, "source": "Row B 111.00 USD"},
        }],
        fields,
        pages,
        monkeypatch,
    )
    by = {l.path: l for l in locs}
    assert by["lines[0].unitPrice"].status == "quote"
    assert min(r[1] for r in by["lines[0].unitPrice"].rects) == 100   # Row A line
    assert by["lines[1].unitPrice"].status == "quote"
    assert min(r[1] for r in by["lines[1].unitPrice"].rects) == 200   # Row B line


def test_numeric_value_beats_misgrounded_quote(monkeypatch):
    """Fix RC-B: a numeric value that matches a single cell (modulo formatting:
    8.165 ⇄ "8.1650") wins step-1 over a MISGROUNDED source quote that points at
    a different row's cell ("10.4900"). The exact #4 bug: unitPrice 8.165 was
    highlighting the adjacent row's 10.4900 because the trailing-zero format
    demoted the value below 1.0, handing control to the wrong quote."""
    fields = [SchemaField(name="unitPrice", type="number", description="p")]
    pages = {
        1: [
            _span("8.1650", bbox=(300, 100, 360, 112)),    # the right cell
            _span("10.4900", bbox=(300, 130, 360, 142)),   # adjacent row (the bad quote)
        ]
    }
    locs = _run(
        [{"unitPrice": 8.165}],
        [{"unitPrice": {"page": 1, "source": "10.4900"}}],  # mis-grounded at wrong row
        fields,
        pages,
        monkeypatch,
    )
    assert locs[0].status in ("exact", "normalized")
    assert locs[0].rects == [[300, 100, 360, 112]]   # 8.1650, not 10.4900


def test_hintless_numeric_value_no_full_doc_scan(monkeypatch):
    """Fix RC-C/RC-D guard: a bare number with NO page hint must NOT roam the
    whole doc and land on the first spurious "0.00" (the tax=0 → page-1 jump, and
    the un-grounded-tab "点哪错哪" explosion). Prefer none over a confident-wrong
    page jump. (A distinctive string with no hint still scans — see
    test_full_doc_scan_when_no_page_hint.)"""
    fields = [SchemaField(name="tax", type="number", description="t")]
    pages = {
        1: [_span("0.00 USD", bbox=(10, 20, 110, 32))],
        3: [_span("0.00 USD", bbox=(10, 20, 110, 32))],
    }
    locs = _run(
        [{"tax": 0}],
        [{"tax": {"page": None, "source": None}}],
        fields,
        pages,
        monkeypatch,
    )
    assert locs[0].status == "none"
    assert locs[0].rects == []


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


def test_decimal_amount_on_string_field_not_distinctive(monkeypatch):
    """A decimal amount stored on a string-typed field ("494.03" — a bad schema
    declaring an amount as string) must NOT distinctive-union its repeats. The
    amount appears on several lines (a line charge + the total row); the source
    quote anchors it to the one labelled total line instead of lighting up every
    occurrence. (A pure-integer code like an invoice number still unions — see
    test_distinctive_string_repeat_unions.)"""
    fields = [SchemaField(name="actual_payment_amount", type="string", description="amt")]
    pages = {
        1: [
            _span("494.03", bbox=(900, 1080, 970, 1100)),    # a line charge
            _span("494.03", bbox=(1050, 1115, 1110, 1135)),  # another line
            _span("总计", bbox=(560, 1165, 600, 1188)),        # total label
            _span("494.03", bbox=(900, 1165, 970, 1188)),    # total row value
        ]
    }
    locs = _run(
        [{"actual_payment_amount": "494.03"}],
        [{"actual_payment_amount": {"page": 1, "source": "总计 494.03"}}],
        fields,
        pages,
        monkeypatch,
    )
    # quote anchors to the 总计 line, not a 4-rect union of every occurrence
    assert locs[0].status == "quote"
    assert all(r[1] >= 1165 for r in locs[0].rects)  # only the total row band


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


def test_short_span_does_not_fuzzy_match_long_value(monkeypatch):
    """A tiny span must not fuzzy-match a long value just by being a digit slice
    of it. The reg number "195101000115 (002060-T)" lives in a letterhead image
    (absent from the text layer), so the only span carrying "15" is a quantity
    cell; partial_ratio scored that 2-char span 100 against the 23-char value and
    lit up the wrong cell. With the comparable-length floor it stays none."""
    fields = [SchemaField(name="bizRegNo", type="string", description="r")]
    pages = {
        1: [
            _span("BROWN STD RIDGE", bbox=(40, 320, 300, 332)),
            _span("15", bbox=(345, 335, 355, 346)),       # quantity cell
            _span("4.9100", bbox=(800, 335, 870, 346)),
        ]
    }
    locs = _run(
        [{"bizRegNo": "195101000115 (002060-T)"}],
        [{"bizRegNo": {"page": 1, "source": "Company No.: 195101000115 (002060-T)"}}],
        fields,
        pages,
        monkeypatch,
    )
    assert locs[0].status == "none"
    assert locs[0].rects == []


def test_low_coverage_quote_fragment_is_not_a_match(monkeypatch):
    """A lone span covering a negligible slice of the source quote is noise, not a
    location. "15" ⊂ "Company No.: 195101000115 (002060-T)" must not be returned
    as a quote hit (it used to win as the only cluster on the page)."""
    fields = [SchemaField(name="bizRegNo", type="string", description="r")]
    pages = {1: [_span("15", bbox=(345, 335, 355, 346))]}
    locs = _run(
        [{"bizRegNo": "195101000115 (002060-T)"}],
        [{"bizRegNo": {"page": 1, "source": "Company No.: 195101000115 (002060-T)"}}],
        fields,
        pages,
        monkeypatch,
    )
    assert locs[0].status == "none"
    assert locs[0].rects == []


def test_quote_still_matches_when_whole_line_present(monkeypatch):
    """Guard against over-tightening: when the letterhead line IS in the text
    layer (warm OCR), the full-coverage quote still resolves cleanly."""
    fields = [SchemaField(name="bizRegNo", type="string", description="r")]
    pages = {
        1: [
            _span("Company No.: 195101000115 (002060-T)", bbox=(205, 72, 552, 80)),
            _span("15", bbox=(345, 335, 355, 346)),  # distractor quantity cell
        ]
    }
    locs = _run(
        [{"bizRegNo": "195101000115 (002060-T)"}],
        [{"bizRegNo": {"page": 1, "source": "Company No.: 195101000115 (002060-T)"}}],
        fields,
        pages,
        monkeypatch,
    )
    # the whole-value substring match on the letterhead line wins; never the cell
    assert locs[0].page == 1
    assert locs[0].rects == [[205.0, 72.0, 552.0, 80.0]]
    assert locs[0].status in ("exact", "quote")
