"""Field-source-grounding resolver: post-hoc text → span alignment.

LangExtract pattern: the Extract LLM only emits *verbatim* text (value +
optional ``source`` quote, both via ``_evidence``). This module does the
post-hoc alignment — match that text against PyMuPDF text-layer spans to
recover the bbox rects where the value lives on the page.

Coordinates (bbox / rects) are produced ONLY here and flow ONLY to the review
render layer. They never enter any LLM prompt. This module backs an HTTP render
endpoint, deliberately NOT a @tool (see app/api/routes/locate.py and
docs/superpowers/INSIGHTS.md #7).

High-precision / low-recall by design: a wrong or shotgun highlight teaches the
user to distrust provenance, so when the source is genuinely ambiguous (the same
value scattered across the page with no disambiguating anchor) we return
``status="none"`` and let the viewer fall back to the page-level button rather
than light up every occurrence.

Match strategy per field:
  source quote (primary)  — the model's own verbatim pointer; text-assembled
                            against spans, the single most specific anchor.
  value (fallback)        — type-aware: numeric fields compare extracted number
                            tokens (never digit-run substrings), dates parse,
                            strings use boundary-aware substring / fuzzy.

Hits are grouped into spatial clusters; a value spanning adjacent lines is ONE
cluster (legit multi-rect), but the same value scattered across the page is many
clusters. We return a single best cluster, or none when the top clusters tie.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Optional

from app.eval.normalize import _try_number, normalize_equivalent
from app.schemas.extraction import evidence_page, evidence_source
from app.schemas.locate import FieldLocation
from app.schemas.schema_field import SchemaField
from app.tools.extract import _collect_leaves
from app.tools.textlayer import extract_textlayer

# rapidfuzz partial-ratio threshold for fuzzy hits (0..100 scale).
_FUZZY_THRESHOLD = 85.0
# Minimum length for a string value (or span fragment) to be allowed to match as
# a substring rather than a full-span equal; shorter values must match exactly
# (avoids "F2" / "USD" lighting up half the page).
_MIN_SUBSTR_LEN = 3
# Strict strength ladder: only a literal full-span-equal hit reaches 1.0, so a
# tie at 1.0 means genuine textual identity (what gates the repeat-union). Lower
# tiers sit strictly below it — substring < normalized < (full-span). All hits of
# the same tier share one strength so several of them tie → ambiguous → none
# rather than an arbitrary pick.
_SUBSTR_STRENGTH = 0.9
_FUZZY_MAX_STRENGTH = 0.8  # fuzzy caps below substring/normalized; never 1.0
# A distinctive string this long, matched full-span-equal in several places, is
# the same entity repeated (e.g. an invoice number in header + stub) → highlight
# all. Shorter or non-exact multi-hits stay ambiguous → none.
_DISTINCTIVE_LEN = 5
# Numeric field types whose value is compared as a number token, never as a
# digit-run substring.
_NUMERIC_TYPES = {"number", "integer", "decimal", "float", "money", "currency", "amount"}
_DATE_TYPES = {"date", "datetime"}
# Pulls number-like tokens out of a span ("Total 111.00 USD" → ["111.00"]).
_NUM_TOKEN = re.compile(r"[-+]?\d[\d.,]*\d|\d")
# Strength gap above which the top cluster is considered a clear winner (so two
# equally-good clusters → ambiguous → none).
_DOMINANCE_EPS = 1e-6
# Ranking of statuses strongest → weakest, for picking a cluster's label.
_STATUS_RANK = {"exact": 4, "normalized": 3, "quote": 2, "fuzzy": 1, "none": 0}


_WS = re.compile(r"\s+")


def _nfkc(s: Any) -> str:
    """NFKC-fold + collapse internal whitespace runs to a single space.

    PyMuPDF text-layer spans carry column-padding artefacts ("SHIM     SHIM",
    "EA        111.00 USD"); the model's verbatim quote does not. Collapsing
    whitespace on both sides lets a clean quote align to a padded span without
    loosening the strength ladder."""
    return _WS.sub(" ", unicodedata.normalize("NFKC", str(s))).strip()


def _value_at_path(entity: dict, path: str) -> Any:
    """Walk a leaf dot-path into an entity dict. Returns None if any hop misses.

    ``_collect_leaves`` emits object children as ``parent.child`` and array
    items as ``parent[]`` / ``parent[].child``. Array leaves have no single
    scalar at the entity root, so they resolve to None here and fall through to
    the document-text scan / quote tiers like any other multi-valued field.
    """
    cur: Any = entity
    for part in path.split("."):
        if part.endswith("[]"):
            # array leaf — no single scalar to pull out
            return None
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _flatten_entity(
    entity: dict,
    schema: list[SchemaField],
) -> list[tuple[str, Any, SchemaField]]:
    """Flatten one entity into ``(dot_path, value, leaf_field)`` tuples.

    Reuses :func:`_collect_leaves` for schema flattening (called per top-level
    field, mirroring ``extract._build_field_instructions``), then pulls each
    leaf's value out of the entity dict by dot-path.
    """
    leaves: list[tuple[str, SchemaField]] = []
    for f in schema:
        if f.name is None:
            continue
        leaves.extend(_collect_leaves(f.name, f))
    out: list[tuple[str, Any, SchemaField]] = []
    for path, leaf in leaves:
        out.append((path, _value_at_path(entity, path), leaf))
    return out


def _fuzzy_score(a_n: str, b_n: str) -> float:
    if not a_n or not b_n:
        return 0.0
    from rapidfuzz import fuzz

    return float(fuzz.partial_ratio(a_n, b_n))


def _field_type(field: SchemaField) -> str:
    t = field.type
    if t is None:
        return "string"
    return str(t.value if hasattr(t, "value") else t).lower()


def _field_is_date(field: SchemaField) -> bool:
    if _field_type(field) in _DATE_TYPES:
        return True
    f = field.format
    fmt = str(f.value if hasattr(f, "value") else f).lower() if f is not None else None
    return fmt in ("date", "date-time", "time")


def _numeric_tokens(text: str) -> list[Decimal]:
    """Extract number-like tokens from span text as Decimals (commas stripped)."""
    out: list[Decimal] = []
    for tok in _NUM_TOKEN.findall(text or ""):
        d = _try_number(tok)
        if d is not None:
            out.append(d)
    return out


def _bounded_substring(needle_n: str, hay_n: str) -> bool:
    """True if ``needle_n`` occurs in ``hay_n`` on word boundaries.

    Prevents mid-word matches ("Air" ⊄ "Airbus") while allowing label-prefixed
    hits ("Acme Corp" ⊂ "Acme Corp Ltd"). Boundaries are non-alphanumeric chars
    (Unicode-aware via ``str.isalnum``).
    """
    start = 0
    while True:
        i = hay_n.find(needle_n, start)
        if i < 0:
            return False
        before = hay_n[i - 1] if i > 0 else ""
        after = hay_n[i + len(needle_n)] if i + len(needle_n) < len(hay_n) else ""
        if not before.isalnum() and not after.isalnum():
            return True
        start = i + 1


# A value worth trying the unannotated-date heuristic on: an ISO-ish date or one
# containing a month name. Keeps the liberal dateparser away from invoice numbers
# / codes that happen to parse as some date.
_ISO_DATE = re.compile(r"\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\b|\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b")
_MONTH_WORD = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", re.IGNORECASE
)


def _looks_like_date(value_n: str) -> bool:
    return bool(_ISO_DATE.search(value_n) or _MONTH_WORD.search(value_n))


def _date_equivalent(value_n: str, span_n: str) -> bool:
    """Heuristic date equality. Spans are line-level ("Date: March 20, 2024"),
    so also try the substring after the last colon."""
    try:
        import dateparser
    except Exception:  # pragma: no cover - dateparser is a hard dep
        return False
    vd = dateparser.parse(value_n, settings={"DATE_ORDER": "YMD"})
    if vd is None:
        return False
    candidates = [span_n]
    if ":" in span_n:
        rhs = span_n.rsplit(":", 1)[-1].strip()
        if rhs and rhs != span_n:
            candidates.append(rhs)
    for cand in candidates:
        pd_ = dateparser.parse(cand, settings={"DATE_ORDER": "YMD"})
        if pd_ is not None and pd_.date() == vd.date():
            return True
    return False


def _value_strength(
    value_n: str,
    value_dec: Optional[Decimal],
    field: SchemaField,
    span_text: str,
) -> tuple[float, str]:
    """Strength (0..1) + status of one field *value* against one span.

    Type-aware. Numeric fields compare extracted number tokens (so ``111`` never
    matches the digit run ``111000012`` and ``0`` never matches ``60674``);
    strings use exact / boundary-aware substring / fuzzy; dates parse.
    """
    span_n = _nfkc(span_text)
    if not span_n or not value_n:
        return 0.0, "none"

    if _field_type(field) in _NUMERIC_TYPES and value_dec is not None:
        for tok in _numeric_tokens(span_n):
            if tok == value_dec:
                return (1.0, "exact") if span_n == value_n else (0.95, "normalized")
        return 0.0, "none"

    if _field_is_date(field):
        return (0.95, "normalized") if _date_equivalent(value_n, span_n) else (0.0, "none")

    # string-like
    if span_n == value_n:
        return 1.0, "exact"
    # boundary-aware substring in either direction: value inside a longer span
    # ("Acme Corp" ⊂ "Acme Corp Ltd") or a span fragment of a longer value (a
    # name wrapped across lines). All substring hits share one strength so that
    # several of them tie → ambiguous → none (never an arbitrary pick).
    if len(value_n) >= _MIN_SUBSTR_LEN and (
        _bounded_substring(value_n, span_n)
        or (len(span_n) >= _MIN_SUBSTR_LEN and _bounded_substring(span_n, value_n))
    ):
        return _SUBSTR_STRENGTH, "exact"
    try:
        if normalize_equivalent(value_n, span_n, field).equivalent:
            return 0.95, "normalized"
    except Exception:
        pass
    # Unannotated date strings: value declared as plain `string` but is really a
    # date ("2024-03-20") that appears as "March 20, 2024" on the page. Only
    # fires when the value itself parses as a date, so non-date strings skip it.
    if _looks_like_date(value_n) and _date_equivalent(value_n, span_n):
        return 0.95, "normalized"
    # Fuzzy is "approximately the same string", not "value is a small fragment of
    # a big span" — partial_ratio would score a short value 100 just for being a
    # substring window ("Air" in "Airbus"). Require the value to be long enough
    # and to cover a fair share of the span before trusting a fuzzy hit. Fuzzy is
    # scaled below the literal/substring/normalized tiers so only a true
    # full-span-equal ever reaches strength 1.0 (which gates the repeat-union).
    if len(value_n) >= _MIN_SUBSTR_LEN and 2 * len(value_n) >= len(span_n):
        sc = _fuzzy_score(value_n, span_n)
        if sc >= _FUZZY_THRESHOLD:
            return _FUZZY_MAX_STRENGTH * (sc / 100.0), "fuzzy"
    return 0.0, "none"


def _quote_span_range(quote_n: str, span_n: str) -> Optional[tuple[int, int]]:
    """The character range of the quote that this span covers, or None.

    A span equal to / containing the whole quote covers ``[0, len(quote))``; a
    span that is a contiguous fragment covers the range where it sits. No fuzzy
    matching — quotes are copied verbatim, so a span must be a real substring to
    count. (Fuzzy partial-ratio used to let "0.00 USD" score against "Total
    111.00 USD", lighting up the wrong line.)"""
    if not span_n or not quote_n:
        return None
    if span_n == quote_n or quote_n in span_n:
        return (0, len(quote_n))
    i = quote_n.find(span_n)
    if i >= 0:
        return (i, i + len(span_n))
    return None


def _merged_len(ranges: list[tuple[int, int]]) -> int:
    """Total length of the union of (possibly overlapping) character ranges."""
    if not ranges:
        return 0
    ranges = sorted(ranges)
    total = 0
    cur_s, cur_e = ranges[0]
    for s, e in ranges[1:]:
        if s <= cur_e:
            cur_e = max(cur_e, e)
        else:
            total += cur_e - cur_s
            cur_s, cur_e = s, e
    return total + (cur_e - cur_s)


def _cluster_quote_lines(spans: list[dict], quote_n: str) -> list[dict]:
    """Group quote-matching spans into *line* clusters and score by coverage.

    A source quote is a horizontal phrase — "Invoice No.: 74671636", "Your P.O.:
    108575201" — whose label and value sit in different columns of the SAME line.
    So (unlike value-wrap clustering, which stacks vertically and needs x-overlap)
    quote fragments are grouped by vertical proximity ONLY, reassembling the whole
    line. A cluster's score is the fraction of the quote's *characters* its
    members cover as a set-union — so a line carrying the value twice (a line-item
    row with net + gross both "111.00 USD") doesn't double-count and beat the real
    "Total 111.00 USD" line. The best-covering line wins and its rects union into
    one whole-line highlight; lines that cover the quote equally (a value that
    genuinely repeats line-for-line) tie → the caller returns none.
    """
    qlen = max(len(quote_n), 1)
    items: list[dict] = []
    for sp in spans:
        rng = _quote_span_range(quote_n, _nfkc(sp.get("text", "")))
        if rng is None:
            continue
        bbox = [float(v) for v in sp.get("bbox", [])]
        if len(bbox) < 4:
            continue
        items.append({"range": rng, "bbox": bbox})
    items.sort(key=lambda it: (it["bbox"][1], it["bbox"][0]))

    clusters: list[dict] = []
    for it in items:
        x0, y0, x1, y1 = it["bbox"]
        h = max(y1 - y0, 1.0)
        cy = (y0 + y1) / 2.0
        placed = False
        for cl in clusters:
            # same line: this span's vertical centre sits within the cluster's
            # band (± ~half a line height). No x-overlap requirement — label and
            # value are in different columns of one line.
            if cl["y0"] - h * 0.6 <= cy <= cl["y1"] + h * 0.6:
                cl["members"].append(it)
                cl["y0"], cl["y1"] = min(cl["y0"], y0), max(cl["y1"], y1)
                placed = True
                break
        if not placed:
            clusters.append({"members": [it], "y0": y0, "y1": y1})

    out: list[dict] = []
    for cl in clusters:
        score = _merged_len([m["range"] for m in cl["members"]]) / qlen
        out.append(
            {"score": score, "status": "quote", "rects": [m["bbox"] for m in cl["members"]]}
        )
    return out


def _cluster_hits(
    spans: list[dict],
    strength_fn: Callable[[str], tuple[float, str]],
) -> list[dict]:
    """Score every span, then group hits into spatial clusters.

    Two hits join a cluster when they are vertically adjacent (within ~one line
    height) and horizontally overlapping — i.e. a value wrapped across lines, or
    a quote spanning lines. Scattered hits stay separate clusters. Each cluster
    is ``{score, status, rects}`` (score = best member strength).
    """
    items: list[dict] = []
    for sp in spans:
        s, status = strength_fn(sp.get("text", ""))
        if s <= 0.0:
            continue
        bbox = [float(v) for v in sp.get("bbox", [])]
        if len(bbox) < 4:
            continue
        items.append({"s": s, "status": status, "bbox": bbox})
    items.sort(key=lambda it: (it["bbox"][1], it["bbox"][0]))

    clusters: list[dict] = []
    for it in items:
        x0, y0, x1, y1 = it["bbox"]
        h = max(y1 - y0, 1.0)
        placed = False
        for cl in clusters:
            gap = y0 - cl["y1"]
            x_overlap = not (x1 < cl["x0"] or x0 > cl["x1"])
            if x_overlap and -h * 0.5 <= gap <= h * 0.8:
                cl["members"].append(it)
                cl["x0"], cl["y0"] = min(cl["x0"], x0), min(cl["y0"], y0)
                cl["x1"], cl["y1"] = max(cl["x1"], x1), max(cl["y1"], y1)
                placed = True
                break
        if not placed:
            clusters.append(
                {"members": [it], "x0": x0, "y0": y0, "x1": x1, "y1": y1}
            )

    out: list[dict] = []
    for cl in clusters:
        members = cl["members"]
        score = max(m["s"] for m in members)
        status = max((m["status"] for m in members), key=lambda st: _STATUS_RANK.get(st, 0))
        out.append({"score": score, "status": status, "rects": [m["bbox"] for m in members]})
    return out


def _select_cluster(
    clusters: list[dict],
    *,
    distinctive: bool = False,
) -> Optional[dict]:
    """Pick the single best cluster, or None when the top clusters tie.

    A clear winner (strictly higher score than the runner-up) is returned. A tie
    at the top usually means the value is ambiguous (the same amount in several
    places) → None, preferring no highlight over a wrong one.

    Exception: a ``distinctive`` value (a long non-numeric string) that matches
    *exactly* (full-span-equal) in several places is the same entity repeated —
    an invoice number in the header and the payment stub, a company name top and
    bottom — so all tied exact clusters are unioned into one location.
    """
    if not clusters:
        return None
    ranked = sorted(clusters, key=lambda c: c["score"], reverse=True)
    if len(ranked) == 1:
        return ranked[0]
    if ranked[0]["score"] > ranked[1]["score"] + _DOMINANCE_EPS:
        return ranked[0]
    # tie at the top
    top = [c for c in ranked if abs(c["score"] - ranked[0]["score"]) <= _DOMINANCE_EPS]
    # Union only literal full-span-equal repeats (score 1.0) of a distinctive
    # value — substring / fuzzy ties (score < 1.0) stay ambiguous → none.
    if distinctive and all(c["score"] >= 1.0 - _DOMINANCE_EPS for c in top):
        rects: list[list[float]] = []
        for c in top:
            rects.extend(c["rects"])
        return {"score": ranked[0]["score"], "status": "exact", "rects": rects}
    return None


async def _page_count(workspace: Path, project_id: str, filename: str) -> int:
    """Best-effort page count via PyMuPDF; 0 if unreadable.

    PDFs report their real page count; image docs (png/jpg) report 1.
    """
    from app.workspace.paths import doc_path

    try:
        import fitz  # PyMuPDF

        src = doc_path(workspace, project_id, filename)
        if str(src).lower().endswith(".pdf"):
            with fitz.open(src) as pdf:
                return int(pdf.page_count)
        return 1
    except Exception:
        return 0


async def _spans_for_page(
    workspace: Path,
    project_id: str,
    filename: str,
    page: int,
    cache: dict[int, list[dict]],
) -> list[dict]:
    """Fetch (and memoize) text-layer spans for one page."""
    if page in cache:
        return cache[page]
    try:
        tl = await extract_textlayer(workspace, project_id, filename, page=page)
        spans = tl.get("spans", []) or []
    except Exception:
        spans = []
    cache[page] = spans
    return spans


async def _locate_one_field(
    workspace: Path,
    project_id: str,
    filename: str,
    *,
    entity_index: int,
    path: str,
    value: Any,
    field: SchemaField,
    page_hint: Optional[int],
    source_quote: Optional[str],
    span_cache: dict[int, list[dict]],
    total_pages: int,
) -> FieldLocation:
    """Resolve one field's rects via the page-hint-first match cascade."""

    def _result(status: str, score: float, rects: list[list[float]], page: Optional[int]):
        return FieldLocation(
            entity_index=entity_index,
            path=path,
            rects=rects,
            page=page,
            status=status,
            score=score,
        )

    def _ordered_pages() -> list[int]:
        pages: list[int] = []
        if page_hint is not None:
            pages.append(page_hint)
        pages.extend(pg for pg in range(1, (total_pages or 0) + 1) if pg != page_hint)
        return pages

    has_value = value is not None and _nfkc(value) != ""
    value_n = _nfkc(value) if has_value else ""
    value_dec = _try_number(value_n) if has_value else None
    # A long value on a string-typed field is distinctive enough that exact
    # repeats are the same entity (an invoice number in header + stub), so they
    # may be unioned. Numeric fields stay collision-collapsed even when long,
    # because a repeated amount is genuinely ambiguous.
    distinctive = (
        has_value
        and _field_type(field) not in _NUMERIC_TYPES
        and len(value_n) >= _DISTINCTIVE_LEN
    )

    async def _value_locate() -> Optional[dict]:
        """Best value-match selection across pages (hint first), or None.

        Returns ``{status, score, rects, page}``. None when the value is absent,
        unmatched, or ambiguous on the hinted page (we don't scatter the search
        across pages once the value is present-but-ambiguous on its own page)."""
        if not has_value:
            return None

        def _vfn(txt: str) -> tuple[float, str]:
            return _value_strength(value_n, value_dec, field, txt)

        if page_hint is not None:
            spans = await _spans_for_page(workspace, project_id, filename, page_hint, span_cache)
            clusters = _cluster_hits(spans, _vfn)
            sel = _select_cluster(clusters, distinctive=distinctive)
            if sel is not None:
                return {**sel, "page": page_hint}
            if clusters:
                return None  # present but ambiguous on the hinted page
        for pg in range(1, (total_pages or 0) + 1):
            if pg == page_hint:
                continue
            spans = await _spans_for_page(workspace, project_id, filename, pg, span_cache)
            sel = _select_cluster(_cluster_hits(spans, _vfn), distinctive=distinctive)
            if sel is not None:
                return {**sel, "page": pg}
        return None

    value_sel = await _value_locate()

    # ---- 1. literal full-value identity first ---------------------------------
    # A full-span-equal value match (score 1.0) — or a distinctive-repeat union of
    # them — is the most trustworthy anchor there is. It outranks the source quote,
    # which the model sometimes points at a logo / letterhead / abbreviation (e.g.
    # billFromName quoted as "AIRBUS" while the real company line sits unmatched).
    if value_sel is not None and value_sel["score"] >= 1.0 - _DOMINANCE_EPS:
        return _result(
            value_sel["status"], value_sel["score"] * 100.0, value_sel["rects"], value_sel["page"]
        )

    # ---- 2. source quote: disambiguates a value that repeats / isn't literal ----
    quote_n = _nfkc(source_quote) if source_quote else ""
    if quote_n:
        for pg in _ordered_pages():
            spans = await _spans_for_page(workspace, project_id, filename, pg, span_cache)
            clusters = _cluster_quote_lines(spans, quote_n)
            sel = _select_cluster(clusters)
            if sel is not None:
                return _result("quote", sel["score"] * 100.0, sel["rects"], pg)
            if clusters:
                break  # quote present on this page but ambiguous → fall to value

    # ---- 3. non-literal value fallback (substring / normalized / fuzzy) --------
    if value_sel is not None:
        return _result(
            value_sel["status"], value_sel["score"] * 100.0, value_sel["rects"], value_sel["page"]
        )

    # ---- nothing matched (or ambiguous) ----
    return _result("none", 0.0, [], page_hint)


# Minimum quote-coverage for the ordinal tie-break to trust a line cluster (so we
# never ordinally assign on a weak label-only match).
_ORDINAL_MIN_SCORE = 0.6


async def _ordinal_tiebreak(
    workspace: Path,
    project_id: str,
    filename: str,
    results: list[FieldLocation],
    field_meta: list[dict],
    span_cache: dict[int, list[dict]],
    total_pages: int,
) -> None:
    """Resolve same-quote sibling fields that tied to ``none`` by document order.

    When several fields share one identical source quote ("Total 111.00 USD" for
    both the net total and the grand total — equal because tax is 0) and that
    quote matches exactly that many equally-good lines, neither value nor quote
    can tell them apart from text alone. We break the tie deterministically by
    *reading order*: the i-th such field (in document/schema order) takes the
    i-th matching line (top-to-bottom). Assumption: field order ≈ document order
    (holds for the usual net-above-grand invoice layout); only fires on an exact
    K-fields ⇄ K-lines tie, so it never scatters a guess.
    """
    from collections import OrderedDict

    groups: "OrderedDict[str, list[dict]]" = OrderedDict()
    for m in field_meta:
        if results[m["ri"]].status != "none" or not m["quote_n"]:
            continue
        groups.setdefault(m["quote_n"], []).append(m)

    for quote_n, members in groups.items():
        if len(members) < 2:
            continue
        hints = [m["page_hint"] for m in members if m["page_hint"]]
        pages: list[int] = []
        if hints:
            pages.append(hints[0])
        pages.extend(pg for pg in range(1, (total_pages or 0) + 1) if pg not in pages)
        for pg in pages:
            spans = await _spans_for_page(workspace, project_id, filename, pg, span_cache)
            clusters = _cluster_quote_lines(spans, quote_n)
            if not clusters:
                continue
            top = max(c["score"] for c in clusters)
            if top < _ORDINAL_MIN_SCORE:
                continue
            tied = [c for c in clusters if abs(c["score"] - top) <= _DOMINANCE_EPS]
            if len(tied) != len(members):
                continue
            tied.sort(key=lambda c: (min(r[1] for r in c["rects"]), min(r[0] for r in c["rects"])))
            for m, cl in zip(members, tied):
                cur = results[m["ri"]]
                results[m["ri"]] = FieldLocation(
                    entity_index=cur.entity_index,
                    path=cur.path,
                    rects=cl["rects"],
                    page=pg,
                    status="quote",
                    score=cl["score"] * 100.0,
                )
            break


async def locate_fields(
    workspace: Path,
    project_id: str,
    filename: str,
    *,
    entities: list[dict],
    evidence: Optional[list[dict]] = None,
    target_lang: Optional[str] = None,
) -> list[FieldLocation]:
    """Locate every leaf field of every entity in the source document.

    ``entities`` / ``evidence`` are the extraction output (raw on-disk shape is
    fine — evidence may be legacy ``{field: int}`` or ``{field: {page, source}}``;
    accessors tolerate both). Returns a flat list of :class:`FieldLocation`,
    one per (entity, leaf-field). ``target_lang`` is accepted for signature
    symmetry with the translate render path (reserved; not used for matching).

    Raises:
        FileNotFoundError: doc sidecar missing (propagated from textlayer when
            a page is actually probed). When the value has no page hint and the
            doc is unreadable, fields degrade to ``status="none"``.
    """
    from app.tools.prompt import read_active_prompt

    pv = await read_active_prompt(workspace, project_id)
    schema: list[SchemaField] = pv.schema

    total_pages = await _page_count(workspace, project_id, filename)
    results: list[FieldLocation] = []

    for idx, entity in enumerate(entities):
        ev_entry = (
            evidence[idx]
            if evidence is not None and idx < len(evidence)
            else None
        )
        # per-document span cache shared across this entity's fields
        span_cache: dict[int, list[dict]] = {}
        field_meta: list[dict] = []
        for path, value, leaf in _flatten_entity(entity, schema):
            page_hint = evidence_page(ev_entry, path) if ev_entry else None
            source_quote = evidence_source(ev_entry, path) if ev_entry else None
            loc = await _locate_one_field(
                workspace,
                project_id,
                filename,
                entity_index=idx,
                path=path,
                value=value,
                field=leaf,
                page_hint=page_hint,
                source_quote=source_quote,
                span_cache=span_cache,
                total_pages=total_pages,
            )
            field_meta.append(
                {
                    "ri": len(results),
                    "quote_n": _nfkc(source_quote) if source_quote else "",
                    "page_hint": page_hint,
                }
            )
            results.append(loc)

        # same-quote sibling fields that tied to none → assign by document order
        await _ordinal_tiebreak(
            workspace, project_id, filename, results, field_meta, span_cache, total_pages
        )

    return results
