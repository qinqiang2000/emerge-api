"""Tests for the quote-location resolver (locate_quotes) + its render route.

Resolver tests mirror test_locate.py: spans are injected by monkeypatching
``extract_textlayer`` + page count, so no real PDF or LLM is needed. Each
"page" is a list of ``{bbox, text, font_size}`` span dicts (the textlayer
shape). Route tests mirror test_locate_route.py: the resolver and the doc
existence check are monkeypatched at the route module, exercising only the
safety + envelope + body plumbing.

locate_quotes deliberately differs from locate_fields in ONE way: the page
hint is searched first but a miss falls back to a whole-doc scan (an audit
judge's page testimony is weaker than the Extract LLM's grounding hint).
Everything else — NFKC fold, string strength ladder, quote-line clustering,
coverage floor, ambiguity → none — is the same machinery.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.locate as locate_route
from app.main import app
from app.schemas.locate import QuoteLocation
from app.tools import locate as locate_mod


# --- fixtures / helpers ------------------------------------------------------


def _span(text: str, bbox=(10.0, 20.0, 110.0, 32.0), size: float = 9.0) -> dict:
    return {"bbox": list(bbox), "text": text, "font_size": size}


def _install(monkeypatch, *, pages: dict[int, list[dict]]):
    """Wire up extract_textlayer and page count via mocks.

    ``pages`` maps 1-based page number → list of span dicts. (Unlike
    locate_fields, locate_quotes never reads the prompt/schema.)
    """

    async def fake_textlayer(ws, pid, fname, *, page, skip_ocr=False):
        assert skip_ocr is True  # warm-sidecar-only discipline
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


def _run(quotes, pages, monkeypatch) -> list[QuoteLocation]:
    _install(monkeypatch, pages=pages)
    return asyncio.run(
        locate_mod.locate_quotes(Path("ws"), "proj", "doc.pdf", quotes=quotes)
    )


# --- exact hit ----------------------------------------------------------------


def test_exact_hit(monkeypatch):
    pages = {1: [_span("Acme Corporation")]}
    locs = _run([{"page": 1, "quote": "Acme Corporation"}], pages, monkeypatch)
    assert len(locs) == 1
    assert locs[0].index == 0
    assert locs[0].status == "exact"
    assert locs[0].page == 1
    assert locs[0].score == 100.0
    assert locs[0].rects == [[10.0, 20.0, 110.0, 32.0]]


# --- normalized hits (NFKC fold / date formatting) ------------------------------


def test_nfkc_fullwidth_quote_matches_halfwidth_span(monkeypatch):
    """A fullwidth/ideographic-space quote (ＡＣＭＥ　Ｃｏｒｐ) must align to the
    halfwidth span via the shared NFKC fold."""
    pages = {1: [_span("ACME Corp", bbox=(40, 60, 140, 72))]}
    locs = _run([{"page": 1, "quote": "ＡＣＭＥ　Ｃｏｒｐ"}], pages, monkeypatch)
    assert locs[0].status in ("exact", "normalized")
    assert locs[0].rects == [[40.0, 60.0, 140.0, 72.0]]


def test_normalized_date_formatting(monkeypatch):
    """An ISO-formatted quote matches the page's prose date via the date
    heuristic → status 'normalized' (the L1-synthesized value-as-quote case)."""
    pages = {1: [_span("March 20, 2024", bbox=(400, 600, 520, 612))]}
    locs = _run([{"page": 1, "quote": "2024-03-20"}], pages, monkeypatch)
    assert locs[0].status == "normalized"
    assert locs[0].rects == [[400.0, 600.0, 520.0, 612.0]]


# --- page hint first, then full-doc fallback -----------------------------------


def test_page_hint_searched_first(monkeypatch):
    """The same quote on pages 1 and 2 with hint=2 must report page 2 (hint
    page wins; never an arbitrary first-page pick)."""
    pages = {
        1: [_span("Total 111.00 USD", bbox=(1, 1, 2, 2))],
        2: [_span("Total 111.00 USD", bbox=(5, 5, 6, 6))],
    }
    locs = _run([{"page": 2, "quote": "Total 111.00 USD"}], pages, monkeypatch)
    assert locs[0].page == 2
    assert locs[0].rects == [[5.0, 5.0, 6.0, 6.0]]


def test_page_hint_miss_falls_back_to_full_doc(monkeypatch):
    """Unlike locate_fields (authoritative hint), a quote that misses its hinted
    page expands to a whole-doc scan and lands where it uniquely sits."""
    pages = {
        1: [_span("cover sheet")],
        2: [_span("table of contents")],
        3: [_span("Acme Corporation", bbox=(9, 9, 19, 19))],
    }
    locs = _run([{"page": 1, "quote": "Acme Corporation"}], pages, monkeypatch)
    assert locs[0].status == "exact"
    assert locs[0].page == 3
    assert locs[0].rects == [[9.0, 9.0, 19.0, 19.0]]


def test_no_hint_scans_whole_doc(monkeypatch):
    pages = {
        1: [_span("cover sheet")],
        2: [_span("Acme Corporation", bbox=(9, 9, 19, 19))],
    }
    locs = _run([{"quote": "Acme Corporation"}], pages, monkeypatch)
    assert locs[0].status == "exact"
    assert locs[0].page == 2


# --- miss → none, never raises --------------------------------------------------


def test_miss_is_none_with_empty_rects(monkeypatch):
    pages = {1: [_span("Totally unrelated text")]}
    locs = _run([{"page": 1, "quote": "Acme Corporation"}], pages, monkeypatch)
    assert locs[0].status == "none"
    assert locs[0].rects == []
    assert locs[0].page == 1  # hint preserved on miss
    assert locs[0].score == 0.0


def test_empty_and_missing_quote_degrade_to_none(monkeypatch):
    """Empty / absent quote text never raises — per-index none results."""
    pages = {1: [_span("Acme Corporation")]}
    locs = _run(
        [{"page": 1, "quote": ""}, {"page": None, "quote": "   "}, {}],
        pages,
        monkeypatch,
    )
    assert [l.index for l in locs] == [0, 1, 2]
    assert all(l.status == "none" and l.rects == [] for l in locs)


def test_unreadable_doc_degrades_to_none(monkeypatch):
    """No pages at all (page count 0, no warm sidecars) → none, no raise."""
    locs = _run([{"page": 1, "quote": "Acme Corporation"}], {}, monkeypatch)
    assert locs[0].status == "none"
    assert locs[0].rects == []


# --- multi-span union ------------------------------------------------------------


def test_cross_column_quote_unions_label_and_value(monkeypatch):
    """A quote whose label and value sit in different columns of one line
    reassembles into ONE quote-line cluster with multiple rects."""
    pages = {
        1: [
            _span("Invoice No.:", bbox=(10, 100, 110, 112)),
            _span("74671636", bbox=(300, 100, 400, 112)),
            _span("nothing here", bbox=(10, 300, 110, 312)),
        ]
    }
    locs = _run([{"page": 1, "quote": "Invoice No.: 74671636"}], pages, monkeypatch)
    assert locs[0].status == "quote"
    assert locs[0].page == 1
    assert sorted(locs[0].rects) == sorted(
        [[10.0, 100.0, 110.0, 112.0], [300.0, 100.0, 400.0, 112.0]]
    )


def test_distinctive_quote_repeat_unions(monkeypatch):
    """A long distinctive quote matched full-span-equal in several places (an
    invoice number in header + stub) is the same entity → all rects union."""
    pages = {
        1: [
            _span("74671636", bbox=(400, 40, 500, 52)),
            _span("unrelated", bbox=(10, 200, 110, 212)),
            _span("74671636", bbox=(50, 700, 150, 712)),
        ]
    }
    locs = _run([{"page": 1, "quote": "74671636"}], pages, monkeypatch)
    assert locs[0].status == "exact"
    assert len(locs[0].rects) == 2


# --- multiple quotes: indices echo input order ------------------------------------


def test_indices_echo_input_order(monkeypatch):
    pages = {
        1: [_span("Acme Corporation", bbox=(10, 20, 110, 32))],
        2: [_span("Total 111.00 USD", bbox=(10, 600, 200, 612))],
    }
    locs = _run(
        [
            {"page": 2, "quote": "Total 111.00 USD"},
            {"page": 1, "quote": "no such text"},
            {"page": 1, "quote": "Acme Corporation"},
        ],
        pages,
        monkeypatch,
    )
    assert [l.index for l in locs] == [0, 1, 2]
    assert locs[0].page == 2 and locs[0].status != "none"
    assert locs[1].status == "none"
    assert locs[2].page == 1 and locs[2].status == "exact"


# --- route: POST .../locate-quotes -------------------------------------------------


@pytest.fixture
def client():
    return TestClient(app)


class _ExistingPath:
    def exists(self):
        return True


class _MissingPath:
    def exists(self):
        return False


def test_route_returns_quote_locations(client, monkeypatch):
    monkeypatch.setattr(locate_route, "doc_path", lambda ws, s, f: _ExistingPath())
    captured = {}

    async def fake_locate_quotes(ws, pid, fname, *, quotes):
        captured["quotes"] = quotes
        return [
            QuoteLocation(
                index=0,
                rects=[[10.0, 20.0, 110.0, 32.0]],
                page=2,
                status="quote",
                score=100.0,
            ),
            QuoteLocation(index=1, rects=[], page=None, status="none", score=0.0),
        ]

    monkeypatch.setattr(locate_route, "locate_quotes", fake_locate_quotes)
    resp = client.post(
        "/lab/projects/acme/docs/by-name/inv.pdf/locate-quotes",
        json={"quotes": [{"page": 2, "quote": "Total 111.00 USD"}, {"quote": "x"}]},
    )
    assert resp.status_code == 200
    bodyj = resp.json()
    assert captured["quotes"] == [
        {"page": 2, "quote": "Total 111.00 USD"},
        {"page": None, "quote": "x"},
    ]
    assert bodyj[0]["index"] == 0
    assert bodyj[0]["status"] == "quote"
    assert bodyj[0]["rects"] == [[10.0, 20.0, 110.0, 32.0]]
    assert bodyj[1]["status"] == "none"
    assert bodyj[1]["rects"] == []


def test_route_doc_not_found(client, monkeypatch):
    monkeypatch.setattr(locate_route, "doc_path", lambda ws, s, f: _MissingPath())
    resp = client.post(
        "/lab/projects/acme/docs/by-name/missing.pdf/locate-quotes",
        json={"quotes": [{"quote": "x"}]},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "doc_not_found"


def test_route_bad_path_400(client, monkeypatch):
    # filename containing a backslash (%5C) fails safe_filename → 400, before
    # any doc existence check or resolver work.
    called = {"doc_path": False}

    def _spy(ws, s, f):
        called["doc_path"] = True
        return _ExistingPath()

    monkeypatch.setattr(locate_route, "doc_path", _spy)
    resp = client.post(
        "/lab/projects/acme/docs/by-name/a%5Cb.pdf/locate-quotes",
        json={"quotes": [{"quote": "x"}]},
    )
    assert resp.status_code == 400
    assert called["doc_path"] is False
