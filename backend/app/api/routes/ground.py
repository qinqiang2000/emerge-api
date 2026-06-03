"""Grounding render-support endpoint (lazy source-quote resolver).

POST /lab/projects/{slug}/docs/by-name/{filename:path}/ground
Runs one grounding LLM pass over a prediction blob's extracted values to recover
per-field ``{page, source}`` evidence, caches it into the blob, and returns it.
The review viewer calls this (when a tab has no evidence yet) before /locate, so
the high-precision locate resolver has its disambiguating anchor.

RENDER-SUPPORT — deliberately NOT a @tool. The grounding *output* is plain text
(page + verbatim quote, never coordinates), so it would not violate the bbox red
line, but there is no agent use case for it: like /locate it backs the review
render layer only. The symmetry invariant enforces "@tool ⇒ route"; a route
without a tool is legitimate and needs no exempt entry. See INSIGHTS.md #7 and
docs/superpowers/plans/2026-05-29-grounding-pass.md.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from app.auth.deps import bind_workspace, current_ws
from pydantic import BaseModel

from app.api.routes._safety import safe_filename, safe_slug
from app.config import get_settings
from app.tools.ground import ground_prediction
from app.workspace.paths import doc_path


router = APIRouter(dependencies=[Depends(bind_workspace)])


class GroundRequest(BaseModel):
    tab: str = "_draft"  # which prediction blob to ground / cache into: _draft | _pending
    force: bool = False  # re-ground even if cached evidence exists
    # The displayed tab's entities. When given, ground these exact values (the
    # merged `active` view may be backed by pending, not the `tab` blob); the
    # result is still cached into `tab` when its entity count matches.
    entities: Optional[list[dict]] = None


class GroundResponse(BaseModel):
    evidence: list[dict]


@router.post("/lab/projects/{slug}/docs/by-name/{filename:path}/ground")
async def post_ground(
    slug: str,
    filename: str,
    body: Optional[GroundRequest] = None,
) -> GroundResponse:
    """Ground a prediction blob's values → cached per-entity evidence.

    Body:
        tab    — ``_draft`` (default) or ``_pending``: which blob to ground.
        force  — re-run even when the blob already has evidence.

    Errors:
        404 `doc_not_found`         — missing doc
        404 `prediction_not_found`  — no prediction blob for that tab
        400 `invalid_path`          — bad slug / filename
    """
    body = body or GroundRequest()
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

    try:
        evidence = await ground_prediction(
            workspace, slug, filename, tab=body.tab, entities=body.entities, force=body.force
        )
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "prediction_not_found", "error_message_en": str(e)},
        ) from e
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "invalid_path", "error_message_en": str(e)},
        ) from e
    except Exception as exc:  # noqa: BLE001 — provider failure envelope
        # Grounding makes a provider call; a transient upstream blip (the flaky
        # 振兴 proxy → httpx.ConnectError) used to escape as a raw 500. Mirror the
        # extract route's envelope so the caller gets a structured, translatable
        # error (and the `transient` flag tells a retry-capable client to re-run).
        from app.provider.retry import is_transient

        transient = is_transient(exc)
        raise HTTPException(
            status_code=503 if transient else 502,
            detail={
                "error_code": (
                    "ground_provider_unavailable" if transient
                    else "ground_provider_failed"
                ),
                "error_message_en": str(exc) or type(exc).__name__,
                "transient": transient,
            },
        ) from exc
    return GroundResponse(evidence=evidence)
