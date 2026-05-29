"""Field-source-grounding resolver: post-hoc text → span alignment.

LangExtract pattern: the Extract LLM only emits *verbatim* text (value +
optional ``source`` quote, both via ``_evidence``). This module does the
post-hoc alignment — match that text against PyMuPDF text-layer spans to
recover the bbox rects where the value lives on the page.

Coordinates (bbox / rects) are produced ONLY here and flow ONLY to the review
render layer. They never enter any LLM prompt. This module backs an HTTP render
endpoint, deliberately NOT a @tool (see app/api/routes/locate.py and
docs/superpowers/INSIGHTS.md #7).

Match cascade per field (page-hint first, then full-document fallback):
  tier 0  exact / fuzzy  — value text vs span text (NFKC, then partial_ratio)
  tier 1  normalized     — type-aware equivalence (date/money/number/enum/…)
  tier 2  quote          — re-run tiers 0/1 using the verbatim ``source`` quote
  none    — value has no literal source in the document
"""

from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Any, Optional

from app.schemas.extraction import evidence_page, evidence_source
from app.schemas.locate import FieldLocation
from app.schemas.schema_field import SchemaField
from app.tools.extract import _collect_leaves
from app.tools.textlayer import extract_textlayer

# rapidfuzz partial-ratio threshold for tier-0 fuzzy hits.
_FUZZY_THRESHOLD = 85.0


def _nfkc(s: Any) -> str:
    return unicodedata.normalize("NFKC", str(s)).strip()


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


def _exact_or_substring(value_n: str, span_text_n: str) -> bool:
    if not value_n or not span_text_n:
        return False
    return value_n == span_text_n or value_n in span_text_n or span_text_n in value_n


def _fuzzy_score(value_n: str, span_text_n: str) -> float:
    if not value_n or not span_text_n:
        return 0.0
    from rapidfuzz import fuzz

    return float(fuzz.partial_ratio(value_n, span_text_n))


def _match_text_in_spans(
    text: str,
    spans: list[dict],
    field: SchemaField,
) -> tuple[str, float, list[list[float]]]:
    """Match ``text`` against page ``spans``, returning (status, score, rects).

    Runs tier-0 (exact / substring / fuzzy) then tier-1 (type-aware normalized
    equivalence). Collects bbox rects from every hitting span (a value can wrap
    across multiple spans). Returns status ``"none"`` with empty rects on miss.
    """
    value_n = _nfkc(text)
    if not value_n:
        return "none", 0.0, []

    # tier 0a: exact / substring
    exact_rects: list[list[float]] = []
    for sp in spans:
        if _exact_or_substring(value_n, _nfkc(sp.get("text", ""))):
            exact_rects.append([float(v) for v in sp.get("bbox", [])])
    if exact_rects:
        return "exact", 100.0, exact_rects

    # tier 0b: fuzzy (partial_ratio per span)
    best_score = 0.0
    fuzzy_rects: list[list[float]] = []
    for sp in spans:
        sc = _fuzzy_score(value_n, _nfkc(sp.get("text", "")))
        if sc >= _FUZZY_THRESHOLD:
            fuzzy_rects.append([float(v) for v in sp.get("bbox", [])])
            best_score = max(best_score, sc)
    if fuzzy_rects:
        return "fuzzy", best_score, fuzzy_rects

    # tier 1: type-aware normalized equivalence.
    # Textlayer spans are line-level, so a "Label: value" span like
    # "Date:   March 20, 2024" cannot be parsed as a date whole.  When the span
    # contains a colon, also try the substring after the last colon so that the
    # value part is isolated for the normalizer.
    from app.eval.normalize import normalize_equivalent

    norm_rects: list[list[float]] = []
    for sp in spans:
        span_text = sp.get("text", "")
        span_n = _nfkc(span_text)
        if not span_n:
            continue
        candidates: list[str] = [span_text]
        if ":" in span_n:
            rhs = span_n.rsplit(":", 1)[-1].strip()
            if rhs and rhs != span_n:
                candidates.append(rhs)
        try:
            matched = any(normalize_equivalent(text, c, field).equivalent for c in candidates)
        except Exception:
            continue
        if matched:
            norm_rects.append([float(v) for v in sp.get("bbox", [])])
    if norm_rects:
        return "normalized", 95.0, norm_rects

    # tier 1.5: heuristic date matching — fires when the extracted value parses
    # as a date even without a "date" format annotation on the SchemaField.
    # This handles schemas where date fields are declared as plain `string`
    # without explicit format metadata.  Candidates include the rhs-split
    # sub-spans already built above (label:value lines).
    try:
        import dateparser

        value_date = dateparser.parse(value_n, settings={"DATE_ORDER": "YMD"})
        if value_date is not None:
            date_rects: list[list[float]] = []
            for sp in spans:
                span_text = sp.get("text", "")
                span_n2 = _nfkc(span_text)
                span_candidates: list[str] = [span_n2]
                if ":" in span_n2:
                    rhs2 = span_n2.rsplit(":", 1)[-1].strip()
                    if rhs2 and rhs2 != span_n2:
                        span_candidates.append(rhs2)
                for cand in span_candidates:
                    parsed = dateparser.parse(cand, settings={"DATE_ORDER": "YMD"})
                    if parsed is not None and parsed.date() == value_date.date():
                        date_rects.append([float(v) for v in sp.get("bbox", [])])
                        break  # only count each span once
            if date_rects:
                return "normalized", 90.0, date_rects
    except Exception:
        pass

    return "none", 0.0, []


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

    has_value = value is not None and _nfkc(value) != ""

    # ---- tiers 0/1 on the page hint, if any ----
    if page_hint is not None and has_value:
        spans = await _spans_for_page(
            workspace, project_id, filename, page_hint, span_cache
        )
        status, score, rects = _match_text_in_spans(str(value), spans, field)
        if status != "none":
            return _result(status, score, rects, page_hint)

    # ---- tiers 0/1 across the whole document (hint missing or missed) ----
    if has_value and total_pages:
        for pg in range(1, total_pages + 1):
            if pg == page_hint:
                continue  # already tried
            spans = await _spans_for_page(
                workspace, project_id, filename, pg, span_cache
            )
            status, score, rects = _match_text_in_spans(str(value), spans, field)
            if status != "none":
                return _result(status, score, rects, pg)

    # ---- tier 2: the verbatim source quote (treat the quote as the value) ----
    if source_quote and _nfkc(source_quote):
        ordered_pages: list[int] = []
        if page_hint is not None:
            ordered_pages.append(page_hint)
        ordered_pages.extend(
            pg for pg in range(1, (total_pages or 0) + 1) if pg != page_hint
        )
        for pg in ordered_pages:
            spans = await _spans_for_page(
                workspace, project_id, filename, pg, span_cache
            )
            status, score, rects = _match_text_in_spans(source_quote, spans, field)
            if status != "none":
                # any source-quote hit is reported as the "quote" tier
                return _result("quote", score, rects, pg)

    # ---- nothing matched ----
    return _result("none", 0.0, [], page_hint)


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
            results.append(loc)

    return results
