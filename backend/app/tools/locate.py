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
from functools import lru_cache
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Optional

from app.eval.normalize import _try_number, normalize_equivalent
from app.schemas.extraction import evidence_page, evidence_source
from app.schemas.locate import FieldLocation, QuoteLocation
from app.schemas.schema_field import SchemaField
from app.tools.extract import _collect_leaves
from app.tools.textlayer import extract_textlayer

# rapidfuzz partial-ratio threshold for fuzzy hits (0..100 scale).
_FUZZY_THRESHOLD = 85.0
# partial_ratio is asymmetric: it scores the SHORTER string as a sliding window
# over the longer one, so a 2-char span ("15") scores 100 against a long value
# ("195101000115 (002060-T)") just for being a substring slice of it. Fuzzy means
# "approximately the same string", not "this tiny fragment occurs inside" — so the
# two must be of comparable length. Require the shorter to be at least this
# fraction of the longer before trusting a fuzzy hit (kills the "15" lights-up-the
# -quantity-cell class of false positive; a real OCR-noise match like
# "Acme Corporatlon Ltd" vs "Acme Corporation" stays well above the floor).
_FUZZY_MIN_LEN_RATIO = 0.5
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
# Strict pass: a space is a hard boundary, so "EA 111.00 USD" → ["111.00"] and
# two amounts on a line don't fuse.
_NUM_TOKEN = re.compile(r"[-+]?\d[\d.,]*\d|\d")
# Spaced pass: CJK / boxed-grid invoices letter-space the digits of ONE number
# ("¥ 1 8 , 6 6 8", "18, 668" → the single amount 18668). After _nfkc any
# whitespace run is already a single space; this regex captures a maximal digit
# run that may carry single intra-run spaces. Whether such a run is really one
# number (fold) or two adjacent ones (keep apart) is decided by _fold_spaced —
# NOT every spaced run fuses: "18 668" / "2 1,500.00" / "2024 12 31" are two
# numbers, a quantity+price, a split date, and fusing them would invent a value
# (18668 / 21500 / 20241231) that scatters or steals an amount field's anchor.
# Additive to the strict pass (results are unioned): we only ever GAIN an
# unambiguous folded reading, never lose the column-split one.
_NUM_TOKEN_SPACED = re.compile(r"[-+]?\d(?: ?[\d.,])*")
# Thousands / decimal grouping separators (a space hugging one is intra-number).
_GROUP_SEP = (",", ".")
# Strength gap above which the top cluster is considered a clear winner (so two
# equally-good clusters → ambiguous → none).
_DOMINANCE_EPS = 1e-6
# Minimum fraction of the source quote a line cluster must cover before the
# primary quote path will trust it. Without a floor, a single incidental fragment
# — a bare "15" that happens to be a substring of "Company No.: 195101000115
# (002060-T)" — forms a lone cluster and _select_cluster returns it regardless of
# how little of the quote it covers, scattering the highlight onto a random
# quantity cell. A genuine match (the whole quote on one line, or its label+value
# fragments unioned) clears this easily; noise fragments don't. Mirrors the
# coverage bars the ordinal / row-anchor passes already apply.
_QUOTE_MIN_COVERAGE = 0.6
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


def _despace(s: str) -> str:
    """Drop ASCII spaces — for quote↔span substring comparison ONLY.

    A model's verbatim source quote and the PyMuPDF text-layer span routinely
    carry DIFFERENT spacing for the same characters: the page prints "34,650 円"
    / "3, 150" (CJK letter-spacing, a space hugging the thousands comma) while
    the model copies "34,650円" / "3,150" (or the reverse). :func:`_nfkc` already
    collapses whitespace *runs* to a single space but cannot delete that lone
    space, so the substring coverage in :func:`_cluster_quote_lines` silently
    misses — and a *repeated* numeric value, whose only disambiguator is that
    quote, then falls all the way to ``none`` (the Kakaku / Hisense-JP invoice
    totalAmount: 34,650 appears as the display row AND two table cells). Matching
    both sides space-free restores the anchor. Coverage stays measured in the
    despaced quote so the fraction math is self-consistent, and the 0.6 floor +
    richer-line-wins + tie→none rules are unchanged — the worst case is
    abstention, never a confident wrong line."""
    return s.replace(" ", "")


_INDEXED = re.compile(r"\[\d+\]")


def _collapse_index(path: str) -> str:
    """`items[0].item` → `items[].item`: the bracket form the grounding evidence
    is keyed by (ground.py collapses concrete indices on reshape)."""
    return _INDEXED.sub("[]", path)


def _value_at_path(entity: Any, path: str) -> Any:
    """Walk a concrete dot-path into an entity; None if any hop misses.

    Handles object children (``parent.child``) and *concrete* array indices
    (``items[0].item``, ``tags[1]``) — the per-row paths produced by
    :func:`_expand_leaf_indices`. The collapsed ``[]`` form never reaches here.
    """
    cur: Any = entity
    for part in path.split("."):
        m = re.fullmatch(r"(.*)\[(\d+)\]", part)
        if m:
            key, idx = m.group(1), int(m.group(2))
            if key:
                cur = cur.get(key) if isinstance(cur, dict) else None
            if not isinstance(cur, list) or idx >= len(cur):
                return None
            cur = cur[idx]
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _expand_leaf_indices(entity: Any, path: str) -> list[str]:
    """Expand a schema leaf path's ``[]`` hops to the concrete indices present in
    the data: ``items[].item`` over a 2-row array → ``items[0].item``,
    ``items[1].item``. A scalar array leaf ``tags[]`` → ``tags[0]`` … Each row
    thus gets its own path + value, so per-row values disambiguate cells that a
    single collapsed slot could not (row 0's "房费" vs row 1's "支付宝").

    An absent / empty array yields no paths (no rows → nothing to highlight)."""
    parts = path.split(".")
    out: list[str] = []

    def rec(node: Any, acc: list[str], rest: list[str]) -> None:
        if not rest:
            out.append(".".join(acc))
            return
        part, tail = rest[0], rest[1:]
        if part.endswith("[]"):
            key = part[:-2]
            seq = node.get(key) if isinstance(node, dict) else None
            if not isinstance(seq, list):
                return
            for i, item in enumerate(seq):
                rec(item, acc + [f"{key}[{i}]"], tail)
        else:
            nxt = node.get(part) if isinstance(node, dict) else None
            rec(nxt, acc + [part], tail)

    rec(entity, [], parts)
    return out


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
        if "[]" in path:
            # one (path, value) per concrete row, so each row's value resolves
            # independently (row 0's cell vs row 1's cell).
            for cpath in _expand_leaf_indices(entity, path):
                out.append((cpath, _value_at_path(entity, cpath), leaf))
        else:
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


def _fold_spaced(run: str) -> Optional[str]:
    """If a spaced digit run is unambiguously ONE number whose spaces are
    intra-number, return it de-spaced; otherwise None (leave the strict groups
    apart). ``run`` is a maximal match of :data:`_NUM_TOKEN_SPACED` over already
    NFKC-collapsed text, so its only spaces are single inter-group spaces.

    A space folds only when it cannot mean "two different numbers next to each
    other":

    - **digit letter-spacing** — both sides are single chars ("1 8 , 6 6 8"); a
      genuine multi-digit number is never printed one-digit-per-cell unless it is
      being letter-spaced;
    - **separator-hugging** — the space sits immediately beside a thousands /
      decimal separator ("18, 668", "18 ,668"); the separator already marks the
      grouping, so the space is just padding.

    A bare space between two multi-digit groups is ambiguous — quantity+price
    ("2 1,500.00"), a split date ("2024 12 31"), two columns ("18 668") — and is
    NOT folded; the strict pass keeps each group as its own token, and we never
    invent a fused value that could steal an amount field's anchor."""
    groups = run.split(" ")
    if len(groups) < 2:
        return None  # no intra-run space — the strict pass already has it
    for left, right in zip(groups, groups[1:]):
        both_single = len(left) == 1 and len(right) == 1
        sep_hugging = left.endswith(_GROUP_SEP) or right.startswith(_GROUP_SEP)
        if not (both_single or sep_hugging):
            return None
    return run.replace(" ", "")


def _numeric_tokens(text: str) -> list[Decimal]:
    """Extract number-like tokens from span text as Decimals.

    Two passes, unioned: the strict pass treats a space as a hard boundary; the
    spaced pass folds a space ONLY when :func:`_fold_spaced` deems it
    intra-number (digit letter-spacing or separator-hugging), so a digit-spaced
    amount ("1 8 , 6 6 8", "18, 668") reads as the one number it is while two
    adjacent numbers stay apart. Commas are stripped as thousands separators in
    both; equality downstream is Decimal-numeric, so trailing-zero precision
    ("123.0" ⇄ "123.0000") already collapses."""
    out: list[Decimal] = []
    seen: set[Decimal] = set()

    def emit(tok: str) -> None:
        d = _try_number(tok)
        if d is not None and d not in seen:
            seen.add(d)
            out.append(d)

    for tok in _NUM_TOKEN.findall(text or ""):
        emit(tok)
    for run in _NUM_TOKEN_SPACED.findall(text or ""):
        folded = _fold_spaced(run)
        if folded is not None:
            emit(folded)
    return out


def _is_decimal_amount(value_n: str, value_dec: Optional[Decimal]) -> bool:
    """True if the value is a number written with a fractional part ("494.03").

    Used to keep a measured amount stored on a string-typed field out of the
    distinctive-repeat union (a repeated amount is ambiguous, not a distinctive
    identifier). A pure-integer code ("74671636") returns False, so invoice
    numbers stay distinctive."""
    return value_dec is not None and "." in value_n


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


# Cheap pre-filter for the dateparser call below. A span is worth a (slow,
# ~10ms) dateparser invocation only if it carries a date-SHAPED token; the 99%
# of spans that are amounts / codes / names get skipped — dateparser would chew
# on them and reject anyway. Deliberately inclusive: separator dates
# (2025-09-23, 23/09/2025, 07-02-25), CJK dates (2025年9月23日), month-word
# dates, and bare yyyymmdd / ddmmyy runs — so the gate never drops a span the
# unfiltered path used to match.
_DATE_GATE = re.compile(
    r"\d{1,4}\s*[-/.年]\s*\d{1,2}\s*[-/.月]\s*\d{1,4}"
    r"|\b\d{6,8}\b"
    r"|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec",
    re.IGNORECASE,
)


def _span_maybe_date(s: str) -> bool:
    return bool(_DATE_GATE.search(s))


@lru_cache(maxsize=8192)
def _parse_date(s: str):
    """``dateparser.parse`` (YMD order), memoised.

    locate scans one field's value against hundreds of spans, and the same value
    + the same spans recur across every entity of a multi-entity doc. dateparser
    is ~10ms/call, so without memoisation a multi-page / multi-entity doc spends
    *minutes* here (cProfile: 84% of locate time). Date parsing is pure, so a
    process-lifetime cache is safe."""
    try:
        import dateparser
    except Exception:  # pragma: no cover - dateparser is a hard dep
        return None
    return dateparser.parse(s, settings={"DATE_ORDER": "YMD"})


def _date_equivalent(value_n: str, span_n: str) -> bool:
    """Heuristic date equality. Spans are line-level ("Date: March 20, 2024"),
    so also try the substring after the last colon. The span is gated by the
    cheap :data:`_DATE_GATE` regex before the (slow) parse — only date-shaped
    spans reach dateparser."""
    vd = _parse_date(value_n)
    if vd is None:
        return False
    candidates = [span_n]
    if ":" in span_n:
        rhs = span_n.rsplit(":", 1)[-1].strip()
        if rhs and rhs != span_n:
            candidates.append(rhs)
    for cand in candidates:
        if not _span_maybe_date(cand):
            continue
        pd_ = _parse_date(cand)
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
                # Numeric token-equality IS value identity regardless of surface
                # formatting (8.165 ⇄ "8.1650", 1500 ⇄ "1,500", 489.9 ⇄ "489.90").
                # BOTH reach the top strength (1.0) so step-1 literal-value-first
                # can win the right cell over a misleading source quote (the
                # collapsed / arbitrary-row quote that used to scatter line-item
                # highlights). A number that genuinely repeats across cells then
                # ties at the top → ambiguous → none (numerics are never
                # distinctive, so _select_cluster won't union them) → handed to the
                # row-anchor / ordinal tie-break. The status keeps the
                # exact/normalized label for telemetry / cluster ranking.
                return (1.0, "exact") if span_n == value_n else (1.0, "normalized")
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
    # a big span" (nor "a tiny span is a slice of a big value") — partial_ratio
    # scores the shorter string as a window over the longer one, so it returns 100
    # for "Air" in "Airbus" OR for "15" in "195101000115 (002060-T)". Require the
    # two to be of comparable length (shorter >= _FUZZY_MIN_LEN_RATIO * longer) and
    # the shorter to clear _MIN_SUBSTR_LEN before trusting a fuzzy hit. Fuzzy is
    # scaled below the literal/substring/normalized tiers so only a true
    # full-span-equal ever reaches strength 1.0 (which gates the repeat-union).
    short_len, long_len = sorted((len(value_n), len(span_n)))
    if short_len >= _MIN_SUBSTR_LEN and short_len >= _FUZZY_MIN_LEN_RATIO * long_len:
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

    Both the quote and each span are matched space-free (see :func:`_despace`):
    the verbatim quote and the text-layer span often disagree on where lone
    spaces fall ("34,650円" vs "34,650 円"), which would otherwise drop the line
    below the coverage floor and lose a repeated value's only anchor.
    """
    quote_ds = _despace(quote_n)
    qlen = max(len(quote_ds), 1)
    items: list[dict] = []
    for sp in spans:
        rng = _quote_span_range(quote_ds, _despace(_nfkc(sp.get("text", ""))))
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
        members = cl["members"]
        # If ONE span already covers the whole quote (a full-line match — e.g. an
        # OCR-recovered "TO : 深圳…有限公司" line), every other matching member is a
        # sub-fragment of that same line: a bare "TO " / ": " label slice, often in
        # the WRONG column (a ": " under SHIP-TO matches the quote's own ": "). Keep
        # only the full-cover span so the highlight is the whole line, not scattered
        # label punctuation. The genuine cross-column label:value case (quote
        # "Invoice No.: 74671636" split across two columns with NO single span
        # covering it whole) is untouched — no member is full-cover, so every
        # fragment is retained and unioned as before.
        full = [m for m in members if m["range"][0] <= 0 and m["range"][1] >= qlen]
        use = full or members
        score = _merged_len([m["range"] for m in use]) / qlen
        out.append(
            {"score": score, "status": "quote", "rects": [m["bbox"] for m in use]}
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


def _rects_overlap(a: list[list[float]], b: list[list[float]]) -> bool:
    """True if any rect in ``a`` intersects any rect in ``b`` (2D bbox overlap).

    Tells whether the value-first match and the source-quote line anchor point at
    the SAME place. When they do NOT, a quote that literally contains the value is
    the model's testimony that the value-first hit is a duplicate elsewhere (the
    bare value in a D/O-No. cell vs the quoted "NO: <inv>" invoice header)."""
    for ra in a:
        if len(ra) < 4:
            continue
        ax0, ay0, ax1, ay1 = ra[0], ra[1], ra[2], ra[3]
        for rb in b:
            if len(rb) < 4:
                continue
            bx0, by0, bx1, by1 = rb[0], rb[1], rb[2], rb[3]
            if not (ax1 < bx0 or bx1 < ax0 or ay1 < by0 or by1 < ay0):
                return True
    return False


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
        # skip_ocr: locate never triggers a Gemini OCR pass itself. OCR on the
        # locate hot path put a multi-second network call (and, when the OCR
        # client is misconfigured, a failing one) on every cold scanned page —
        # the dominant "卡死" cost when scanning a doc whose sidecars aren't warm
        # yet. The review viewer warms OCR sidecars separately (GET /textlayer);
        # locate reads whatever is warm and stays pure-CPU otherwise, so it can
        # run off the event loop (see the route's to_thread offload).
        tl = await extract_textlayer(workspace, project_id, filename, page=page, skip_ocr=True)
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
        # The evidence page hint is the model's testimony of WHERE it read the
        # value — it is authoritative. When present, search ONLY that page; never
        # relocate a field onto another page. In a multi-invoice doc the seller
        # boilerplate (country, reg#, TIN, company name) is byte-identical on every
        # invoice, so a whole-doc scan would "find" the value on some OTHER
        # invoice's letterhead and teleport the highlight to the wrong page (the
        # p17→p5 drift). The hint is the only thing that disambiguates the copies,
        # so leaving it is always wrong. Whole-doc scan runs ONLY when there is no
        # hint at all (legacy / derived fields).
        if page_hint is not None:
            return [page_hint]
        return list(range(1, (total_pages or 0) + 1))

    has_value = value is not None and _nfkc(value) != ""
    value_n = _nfkc(value) if has_value else ""
    value_dec = _try_number(value_n) if has_value else None
    # A long value on a string-typed field is distinctive enough that exact
    # repeats are the same entity (an invoice number in header + stub), so they
    # may be unioned. Numeric fields stay collision-collapsed even when long,
    # because a repeated amount is genuinely ambiguous.
    #
    # The ``_is_decimal_amount`` guard also collapses a *decimal* number stored on
    # a string-typed field (an amount "494.03" the schema declares as string): a
    # value with a fractional part is a measured amount, and a repeat is the same
    # amount appearing several times (a line charge + the total row), NOT a
    # distinctive identifier — don't union; let the quote anchor pick the one
    # right line or fall back to none. A pure-integer code ("74671636") has no
    # decimal point, so an invoice number stays distinctive and still unions.
    distinctive = (
        has_value
        and _field_type(field) not in _NUMERIC_TYPES
        and not _is_decimal_amount(value_n, value_dec)
        and len(value_n) >= _DISTINCTIVE_LEN
    )

    async def _value_locate() -> Optional[dict]:
        """Best value-match selection, or None.

        Returns ``{status, score, rects, page}``. Confined to the hinted page when
        a hint exists (the hint is authoritative — see ``_ordered_pages``); only a
        hint-less field scans the whole doc. None when the value is absent,
        unmatched, or ambiguous on the searched page(s)."""
        if not has_value:
            return None

        # No page hint → _ordered_pages roams the WHOLE doc. A bare number or
        # short value with no hint matches a spurious early-page token (tax=0 →
        # page-1 "0.00"; quantity 60 → "Net 60 days"; and an entirely un-grounded
        # tab makes EVERY field do this → "点哪错哪"). Confine the hint-less roam
        # to a DISTINCTIVE value — a long non-numeric identifier that is the same
        # entity wherever it appears; everything else with no hint stays none.
        # Prefer no highlight over a confident-wrong page jump. Hinted fields are
        # unaffected (they search only their page); once the blob is grounded
        # every quoted field has a hint, so this only guards derived / un-grounded
        # values.
        if page_hint is None and not distinctive:
            return None

        def _vfn(txt: str) -> tuple[float, str]:
            return _value_strength(value_n, value_dec, field, txt)

        for pg in _ordered_pages():
            spans = await _spans_for_page(workspace, project_id, filename, pg, span_cache)
            sel = _select_cluster(_cluster_hits(spans, _vfn), distinctive=distinctive)
            if sel is not None:
                return {**sel, "page": pg}
        return None

    value_sel = await _value_locate()

    # Resolve the source-quote line anchor ONCE (the corroboration gate below and
    # the step-3 quote fallback both read it). Mirrors the old inline step-2 loop:
    # the first page carrying a single dominant ≥coverage line wins; a page that
    # carries the quote only ambiguously stops the scan (no anchor → fall to value).
    quote_n = _nfkc(source_quote) if source_quote else ""
    quote_sel: Optional[dict] = None
    quote_pg: Optional[int] = None
    if quote_n:
        for pg in _ordered_pages():
            spans = await _spans_for_page(workspace, project_id, filename, pg, span_cache)
            # Keep only clusters that cover a real share of the quote; a lone
            # low-coverage fragment ("15" ⊂ the quote's digits) is noise, not a
            # presence of the quote, so it must not win nor stop the page scan.
            clusters = [
                c for c in _cluster_quote_lines(spans, quote_n)
                if c["score"] >= _QUOTE_MIN_COVERAGE
            ]
            sel = _select_cluster(clusters)
            if sel is not None:
                quote_sel, quote_pg = sel, pg
                break
            if clusters:
                break  # quote present on this page but ambiguous → no anchor

    # ---- 1. corroborated quote anchor (narrow override of value-first) --------
    # Fire ONLY when value-first is about to light up a full-span-equal hit on a
    # line the model did NOT quote, while a source quote that literally CONTAINS
    # the value resolves to a single OTHER line. That is exactly the repeated-value
    # bug: invoice number "KB060162" sits full-span (score 1.0) in a D/O-No. cell
    # *and* as a substring (0.9) inside the quoted "NO: KB060162" header, so the
    # bare cell would win value-first and the highlight teleports to the wrong row.
    # The model's own verbatim quote pinpoints which occurrence it read.
    #
    # Every guard keeps the blast radius to that one case:
    #   • `value_n in quote_n` — the quote really contains the value. Preserves the
    #     misleading-quote case value-first was built for (billFromName quoted as
    #     the logo "AIRBUS" while the real company line sits elsewhere — the quote
    #     does NOT contain "Airbus Operations GmbH"), so we fall through unchanged.
    #   • `not _rects_overlap(...)` — value-first and the quote point at DIFFERENT
    #     places. When they coincide (the common label:value-on-one-line field),
    #     this is False and behaviour is byte-identical to before (value-first
    #     wins, value-only rect, status "exact").
    if (
        quote_sel is not None
        and value_sel is not None
        and value_sel["score"] >= 1.0 - _DOMINANCE_EPS
        and has_value and value_n and value_n in quote_n
        and not _rects_overlap(value_sel["rects"], quote_sel["rects"])
    ):
        return _result("quote", quote_sel["score"] * 100.0, quote_sel["rects"], quote_pg)

    # ---- 2. literal full-value identity ---------------------------------------
    # A full-span-equal value match (score 1.0) — or a distinctive-repeat union of
    # them — is the most trustworthy anchor when the quote does NOT corroborate a
    # single OTHER line. It outranks the (uncorroborated) source quote, which the
    # model sometimes points at a logo / letterhead / abbreviation (billFromName
    # quoted as "AIRBUS" while the real company line sits unmatched).
    if value_sel is not None and value_sel["score"] >= 1.0 - _DOMINANCE_EPS:
        return _result(
            value_sel["status"], value_sel["score"] * 100.0, value_sel["rects"], value_sel["page"]
        )

    # ---- 3. source quote: disambiguates a value that repeats / isn't literal ----
    if quote_sel is not None:
        return _result("quote", quote_sel["score"] * 100.0, quote_sel["rects"], quote_pg)

    # ---- 4. non-literal value fallback (substring / normalized / fuzzy) --------
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

    Fields are grouped by ``(parent_path, quote)`` — siblings only — never by the
    quote alone. The reading-order assumption is defensible only among siblings;
    lumping unrelated fields together (a top-level ``currency`` that grounding gave
    the bogus quote "111.00 USD" alongside the line-item ``netAmount`` / ``grossAmount``
    that legitimately carry it) used to manufacture a K⇄K tie and assign the
    line-item amounts to the document's grand-total lines. Sibling-scoping keeps
    each genuine repeat-set (the two top-level totals; the line-item amounts) on
    its own, so a coincidental cross-kind collision no longer fires.
    """
    from collections import OrderedDict

    def _parent(path: str) -> str:
        return path.rsplit(".", 1)[0] if "." in path else ""

    groups: "OrderedDict[tuple[str, str], list[dict]]" = OrderedDict()
    for m in field_meta:
        if results[m["ri"]].status != "none" or not m["quote_n"]:
            continue
        groups.setdefault((_parent(results[m["ri"]].path), m["quote_n"]), []).append(m)

    for (_parent_path, quote_n), members in groups.items():
        if len(members) < 2:
            continue
        # Hint is authoritative (see _ordered_pages): confine the tie-break to the
        # siblings' hinted page; only a hint-less group scans the whole doc.
        hints = [m["page_hint"] for m in members if m["page_hint"]]
        pages = [hints[0]] if hints else list(range(1, (total_pages or 0) + 1))
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


def _dedupe_aggregate_rects(rects: list[list[float]]) -> list[list[float]]:
    """Drop line-aggregate rects that enclose their own constituent word rects.

    On an electronic page the text layer can carry BOTH a fitz line-level span
    ("SHIM     SHIM", "EA 111.00 USD 111.00 USD") and OCR word-level spans
    ("SHIM", "111.00 USD") for the same content (OCR runs to catch logos and its
    word split survives the center-point dedupe). Matching both paints a wide
    ring drawn over two tight rings — clutter that occludes the value. When one
    rect geometrically encloses the centres of >=2 OTHER, strictly-narrower
    rects, it is that line aggregate; drop it and keep the tight word rects. A
    single clean span (the common case) or vertically-stacked wrap rects enclose
    nothing → untouched."""
    if len(rects) <= 1:
        return rects

    def cx(r: list[float]) -> float:
        return (r[0] + r[2]) / 2.0

    def cy(r: list[float]) -> float:
        return (r[1] + r[3]) / 2.0

    keep: list[list[float]] = []
    for i, R in enumerate(rects):
        enclosed = 0
        for j, r in enumerate(rects):
            if i == j:
                continue
            if (
                R[0] <= cx(r) <= R[2]
                and R[1] <= cy(r) <= R[3]
                and (r[2] - r[0]) < (R[2] - R[0])
            ):
                enclosed += 1
        if enclosed < 2:
            keep.append(R)
    return keep or rects


# A none array-child line cluster is accepted by the row anchor only when its
# quote coverage clears this bar (so we never anchor on a weak label-only hit).
_ROW_ANCHOR_MIN_SCORE = 0.6
# Max vertical distance (PDF points) the nearest matching line may sit from the
# row's anchor before the row anchor refuses (the row's cell should be on or
# very near the anchor's line; a far match is a different row / a grand total).
_ROW_ANCHOR_MAX_GAP = 40.0


async def _row_anchor(
    workspace: Path,
    project_id: str,
    filename: str,
    results: list[FieldLocation],
    field_meta: list[dict],
    span_cache: dict[int, list[dict]],
    total_pages: int,
) -> None:
    """Resolve ambiguous array-child fields by their resolved row neighbours.

    A line-item amount ("111.00 USD", "494.03") repeats across the page — the
    row's own columns AND the document grand totals — with no quote unique enough
    to disambiguate, so it lands on none. But its siblings on the SAME concrete
    row (``items[0].item`` = "房费") usually resolve, pinning that row's y. For a
    none field we pick the quote cluster whose line is *nearest* the row's anchor
    y — so ``items[0].subtotal`` takes the 494.03 on row 0's line, ``items[1]``
    the one on row 1, and a line-item amount takes its row, not the grand total.

    Per concrete row (``items[0]`` ≠ ``items[1]``): nearest-y, not a padded band,
    because adjacent rows sit only ~one line apart and a band would bridge them.
    Gated hard so it only ever turns a none into a row-local hit: array-children
    only; needs a resolved sibling in the SAME row; the chosen cluster must clear
    the coverage bar, sit within ``_ROW_ANCHOR_MAX_GAP`` of the anchor, and be
    strictly nearer than the runner-up (an equidistant tie → leave it none).
    """
    meta_by_ri = {m["ri"]: m for m in field_meta}

    def _row_parent(path: str) -> Optional[str]:
        # concrete-row child "items[0].item" → row "items[0]"; else not an array child
        return path.rsplit(".", 1)[0] if re.search(r"\[\d+\]\.", path) else None

    # Anchor y per concrete row = mean centre of that row's resolved children.
    anchors: dict[str, list[float]] = {}
    line_h: dict[str, float] = {}
    by_parent_none: dict[str, list[FieldLocation]] = {}
    for loc in results:
        parent = _row_parent(loc.path)
        if parent is None:
            continue
        if loc.status != "none" and loc.rects:
            anchors.setdefault(parent, []).append(
                sum((r[1] + r[3]) / 2.0 for r in loc.rects) / len(loc.rects)
            )
            line_h[parent] = max(line_h.get(parent, 0.0), max(r[3] - r[1] for r in loc.rects))
        elif loc.status == "none":
            by_parent_none.setdefault(parent, []).append(loc)

    for parent, none_locs in by_parent_none.items():
        ys = anchors.get(parent)
        if not ys:
            continue  # no resolved sibling to anchor against
        anchor_y = sum(ys) / len(ys)
        gap = max(_ROW_ANCHOR_MAX_GAP, 2.0 * line_h.get(parent, 0.0))
        for loc in none_locs:
            ri = next((i for i, r in enumerate(results) if r is loc), None)
            if ri is None:
                continue
            meta = meta_by_ri.get(ri)
            if not meta or not meta["quote_n"]:
                continue
            page = meta["page_hint"]
            pages = [page] if page else list(range(1, (total_pages or 0) + 1))
            for pg in pages:
                spans = await _spans_for_page(workspace, project_id, filename, pg, span_cache)
                clusters = [
                    c for c in _cluster_quote_lines(spans, meta["quote_n"])
                    if c["score"] >= _ROW_ANCHOR_MIN_SCORE
                ]
                if not clusters:
                    continue
                def _dist(c: dict) -> float:
                    cy = sum((r[1] + r[3]) / 2.0 for r in c["rects"]) / len(c["rects"])
                    return abs(cy - anchor_y)
                clusters.sort(key=_dist)
                nearest = clusters[0]
                if _dist(nearest) > gap:
                    break  # closest matching line is too far from the row → none
                # require a clear winner: runner-up at least half a line further
                if len(clusters) > 1 and _dist(clusters[1]) - _dist(nearest) < line_h.get(parent, 12.0) * 0.5:
                    break
                results[ri] = FieldLocation(
                    entity_index=loc.entity_index,
                    path=loc.path,
                    rects=nearest["rects"],
                    page=pg,
                    status="quote",
                    score=nearest["score"] * 100.0,
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

    # Span cache is document-global — page spans don't depend on the entity, so
    # share it across ALL entities. Per-entity it would re-read (json.loads) each
    # page's textlayer sidecar once per entity; a 14-entity × 28-page doc thus
    # re-parsed sidecars ~hundreds of times for no reason.
    span_cache: dict[int, list[dict]] = {}
    for idx, entity in enumerate(entities):
        ev_entry = (
            evidence[idx]
            if evidence is not None and idx < len(evidence)
            else None
        )
        field_meta: list[dict] = []
        for path, value, leaf in _flatten_entity(entity, schema):
            # Evidence is keyed by the collapsed `items[].child` form (ground.py
            # collapses concrete indices); try the exact concrete key first (for
            # any future per-row grounding) then fall back to the collapsed one.
            ev_key = path if (ev_entry and path in ev_entry) else _collapse_index(path)
            page_hint = evidence_page(ev_entry, ev_key) if ev_entry else None
            source_quote = evidence_source(ev_entry, ev_key) if ev_entry else None
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
        # array-children still none → anchor to their resolved row neighbours
        await _row_anchor(
            workspace, project_id, filename, results, field_meta, span_cache, total_pages
        )

    # Final render-quality sweep: collapse the fitz-line + OCR-word rect overlap
    # into tight word rects so highlights never paint a wide ring over narrow
    # ones (see _dedupe_aggregate_rects).
    for i, loc in enumerate(results):
        if len(loc.rects) > 1:
            deduped = _dedupe_aggregate_rects(loc.rects)
            if len(deduped) != len(loc.rects):
                results[i] = loc.model_copy(update={"rects": deduped})

    return results


# ---------------------------------------------------------------------------
# locate_quotes — standalone "verbatim quote → page rects" resolver
# ---------------------------------------------------------------------------
# A quote here is exactly what the field path calls a tier-2 *source quote*
# (audit `RuleCheck.evidence` quotes, board annotations, …), decoupled from any
# (entity, field-path) pair. It reuses the SAME span-matching tiers — NFKC
# normalisation, exact / boundary-substring / rapidfuzz fuzzy string strength
# (`_value_strength`), and the despaced quote-line clustering with its coverage
# floor (`_cluster_quote_lines` + `_QUOTE_MIN_COVERAGE`) — without touching
# `locate_fields` or its precision tuning.
#
# One deliberate divergence: `locate_fields` treats the evidence page hint as
# authoritative (the Extract LLM's testimony of where it READ the value), but
# an audit judge's / annotator's page hint is weaker testimony — so here the
# hint page is searched FIRST and a miss falls back to a whole-doc scan.
#
# Same render-only hard rule: rects flow only through the locate-quotes HTTP
# route (app/api/routes/locate.py), never into any prompt / tool result.

# Pseudo string field handed to `_value_strength` so a quote rides the string
# strength ladder (exact / substring / normalized / date-heuristic / fuzzy).
_QUOTE_FIELD = SchemaField(
    name="quote", type="string", description="verbatim quote (locate_quotes pseudo-field)"
)


async def _locate_one_quote(
    workspace: Path,
    project_id: str,
    filename: str,
    *,
    index: int,
    quote: Any,
    page_hint: Optional[int],
    span_cache: dict[int, list[dict]],
    total_pages: int,
) -> QuoteLocation:
    """Resolve one verbatim quote's rects: hint page first, then whole doc.

    Per page, the cascade mirrors `_locate_one_field` steps 2–4 (the quote IS
    both the "value" and the "source quote" here, so the step-1 corroboration
    gate is moot):
      1. literal full-span identity (score 1.0 — incl. distinctive-repeat
         union) → exact / normalized;
      2. quote-line cluster clearing the coverage floor → quote (label+value
         split across columns reassembles into one multi-rect line);
      3. weaker string strength (substring / normalized / fuzzy) → its status.
    A page where every tier abstains (no hit, or ambiguous tie → none) does not
    stop the scan; a fully-missed quote degrades to status "none" — never an
    exception.
    """

    def _result(
        status: str, score: float, rects: list[list[float]], page: Optional[int]
    ) -> QuoteLocation:
        return QuoteLocation(index=index, rects=rects, page=page, status=status, score=score)

    quote_n = _nfkc(quote) if isinstance(quote, str) else ""
    if not quote_n:
        return _result("none", 0.0, [], page_hint)

    quote_dec = _try_number(quote_n)
    # Same distinctiveness rule as a string-typed field: a long non-amount
    # string repeated full-span-equal is the same entity → union; a decimal
    # amount repeats ambiguously → tie stays none.
    distinctive = (
        not _is_decimal_amount(quote_n, quote_dec)
        and len(quote_n) >= _DISTINCTIVE_LEN
    )

    def _qfn(txt: str) -> tuple[float, str]:
        return _value_strength(quote_n, quote_dec, _QUOTE_FIELD, txt)

    pages: list[int] = []
    if page_hint is not None:
        pages.append(page_hint)
    pages.extend(p for p in range(1, (total_pages or 0) + 1) if p != page_hint)

    for pg in pages:
        spans = await _spans_for_page(workspace, project_id, filename, pg, span_cache)
        if not spans:
            continue
        sel_v = _select_cluster(_cluster_hits(spans, _qfn), distinctive=distinctive)
        # literal full-span identity is the most trustworthy anchor
        if sel_v is not None and sel_v["score"] >= 1.0 - _DOMINANCE_EPS:
            return _result(sel_v["status"], sel_v["score"] * 100.0, sel_v["rects"], pg)
        # quote-line reassembly (cross-column label+value fragments union into
        # one line); the coverage floor keeps incidental fragments out.
        qclusters = [
            c
            for c in _cluster_quote_lines(spans, quote_n)
            if c["score"] >= _QUOTE_MIN_COVERAGE
        ]
        sel_q = _select_cluster(qclusters)
        if sel_q is not None:
            return _result("quote", sel_q["score"] * 100.0, sel_q["rects"], pg)
        # non-literal string fallback (substring / normalized / fuzzy)
        if sel_v is not None:
            return _result(sel_v["status"], sel_v["score"] * 100.0, sel_v["rects"], pg)

    return _result("none", 0.0, [], page_hint)


async def locate_quotes(
    workspace: Path,
    project_id: str,
    filename: str,
    *,
    quotes: list[dict],
) -> list[QuoteLocation]:
    """Locate verbatim quotes in the source document (render-only).

    ``quotes`` items are ``{page?: int|None, quote: str}`` — the page is an
    optional hint searched first; a miss falls back to a whole-doc scan.
    Returns one :class:`QuoteLocation` per input, in input order (``index``
    echoes the input position). Missing / empty / unmatched quotes degrade to
    ``status="none"`` with empty rects — never an exception.

    Reads warm textlayer sidecars only (``skip_ocr=True`` via
    `_spans_for_page`): pure CPU + file IO, safe to run on a worker thread off
    the event loop (see the route's ``to_thread`` offload).
    """
    total_pages = await _page_count(workspace, project_id, filename)
    # Document-global span cache, shared across all quotes (same rationale as
    # locate_fields: page spans don't depend on the quote).
    span_cache: dict[int, list[dict]] = {}

    out: list[QuoteLocation] = []
    for idx, item in enumerate(quotes):
        raw_page = item.get("page") if isinstance(item, dict) else None
        page_hint = (
            raw_page
            if isinstance(raw_page, int) and not isinstance(raw_page, bool) and raw_page >= 1
            else None
        )
        loc = await _locate_one_quote(
            workspace,
            project_id,
            filename,
            index=idx,
            quote=item.get("quote") if isinstance(item, dict) else None,
            page_hint=page_hint,
            span_cache=span_cache,
            total_pages=total_pages,
        )
        out.append(loc)

    # Same render-quality sweep as locate_fields: collapse fitz-line + OCR-word
    # rect overlap into tight word rects.
    for i, loc in enumerate(out):
        if len(loc.rects) > 1:
            deduped = _dedupe_aggregate_rects(loc.rects)
            if len(deduped) != len(loc.rects):
                out[i] = loc.model_copy(update={"rects": deduped})

    return out
