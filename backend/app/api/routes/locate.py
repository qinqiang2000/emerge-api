"""Field-source-grounding locate render endpoints (thin-delegate).

POST /lab/projects/{slug}/docs/by-name/{filename:path}/locate
Returns per-field bbox rects (PDF point units) for the review viewer to paint
"jump to source" highlights. Mirrors the textlayer / translate routes: safe
slug/filename, 404/400 envelope.

POST /lab/projects/{slug}/docs/by-name/{filename:path}/locate-quotes
Same machinery decoupled from field paths: verbatim quotes (audit
``RuleCheck.evidence``, board annotations) → page rects, for the audit board /
synthetic board render / MCP App to paint.

RENDER-ONLY — these are deliberately NOT registered as @tools. The responses
carry bbox ``rects``; exposing them as agent tools would leak coordinates into
the agent SDK context, violating the CLAUDE.md hard rule that bbox /
coordinates never enter any LLM prompt (INSIGHTS.md "field-source-grounding:
source is TEXT, locate is a render route"). The symmetry invariant
(test_symmetry_invariant.py) only enforces "@tool ⇒ route"; a route without a
tool is legitimate and needs no exempt entry.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from app.auth.deps import bind_workspace, current_ws
from pydantic import BaseModel

from app.api.routes._safety import safe_filename, safe_slug
from app.config import get_settings
from app.schemas.locate import FieldLocation, QuoteLocation
from app.tools.locate import locate_fields, locate_quotes
from app.workspace.paths import doc_path


router = APIRouter(dependencies=[Depends(bind_workspace)])


class LocateRequest(BaseModel):
    entities: list[dict]
    evidence: Optional[list[dict]] = None


@router.post("/lab/projects/{slug}/docs/by-name/{filename:path}/locate")
async def post_locate(
    slug: str,
    filename: str,
    body: LocateRequest,
    lang: Optional[str] = Query(None),
) -> list[FieldLocation]:
    """Return `list[FieldLocation]` — per (entity, leaf-field) bbox rects.

    Body:
        entities  — the displayed tab's entity list (tab-agnostic, stateless)
        evidence  — the parallel `_evidence` list (legacy int or {page,source});
                    may be null

    Query params:
        lang  — optional target language (reserved; render symmetry with translate)

    Errors:
        404 `doc_not_found`  — missing doc
        400 `invalid_path`   — bad slug / filename
    """
    safe_slug(slug)
    safe_filename(filename)
    settings = get_settings()
    workspace = current_ws()

    if not doc_path(workspace, slug, filename).exists():
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "doc_not_found",
                "error_message_en": f"no doc named {filename!r} in project {slug!r}",
            },
        )

    # locate is CPU-bound (rapidfuzz / clustering / dateparser) and its textlayer
    # reads are warm-sidecar file reads — i.e. it does NO real async I/O and would
    # otherwise run start-to-finish WITHOUT yielding, blocking the event loop for
    # its full duration. Under rapid doc-switching that froze the whole backend
    # (review-form GETs queued behind it → "加载中…" / "正在定位来源…" stuck). Run it
    # on a worker thread so the loop stays responsive; with skip_ocr the work is
    # pure-CPU + file reads, so a fresh per-call loop in the thread is safe.
    def _run() -> list[FieldLocation]:
        return asyncio.run(
            locate_fields(
                workspace,
                slug,
                filename,
                entities=body.entities,
                evidence=body.evidence,
                target_lang=lang,
            )
        )

    try:
        locations = await asyncio.to_thread(_run)
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "doc_not_found", "error_message_en": str(e)},
        ) from e
    return [loc.model_dump() for loc in locations]


class QuoteItem(BaseModel):
    page: Optional[int] = None
    quote: str


class LocateQuotesRequest(BaseModel):
    quotes: list[QuoteItem]


@router.post("/lab/projects/{slug}/docs/by-name/{filename:path}/locate-quotes")
async def post_locate_quotes(
    slug: str,
    filename: str,
    body: LocateQuotesRequest,
) -> list[QuoteLocation]:
    """Return `list[QuoteLocation]` — per input-index bbox rects for verbatim quotes.

    Body:
        quotes  — list of `{page?, quote}`; `page` is an optional hint searched
                  first, a miss falls back to a whole-doc scan. Results echo the
                  input order via `index`; unmatched quotes degrade to
                  `status="none"` (never an error).

    Errors:
        404 `doc_not_found`  — missing doc
        400 `invalid_path`   — bad slug / filename
    """
    safe_slug(slug)
    safe_filename(filename)
    workspace = current_ws()

    if not doc_path(workspace, slug, filename).exists():
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "doc_not_found",
                "error_message_en": f"no doc named {filename!r} in project {slug!r}",
            },
        )

    # Same event-loop discipline as /locate (INSIGHTS "/locate must run OFF the
    # event loop"): the resolver is CPU-bound (rapidfuzz / clustering) and its
    # textlayer reads are warm-sidecar file reads with no real await inside —
    # run start-to-finish on the loop it would block every other request for
    # its full duration. skip_ocr=True is baked into the resolver's span reads,
    # so the threaded work is pure-CPU + file IO and a fresh per-call loop in
    # the worker thread is safe (no provider client crosses loops).
    def _run() -> list[QuoteLocation]:
        return asyncio.run(
            locate_quotes(
                workspace,
                slug,
                filename,
                quotes=[q.model_dump() for q in body.quotes],
            )
        )

    try:
        locations = await asyncio.to_thread(_run)
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "doc_not_found", "error_message_en": str(e)},
        ) from e
    return [loc.model_dump() for loc in locations]
