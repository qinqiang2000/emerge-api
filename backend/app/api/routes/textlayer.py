"""HTTP route for the per-page PDF text layer.

Thin-delegate mirror of the `extract_textlayer` MCP tool so the frontend
review overlay (and any CLI client) can pull text spans over plain HTTP.

The text layer is review-UX only — bbox + spans NEVER reach the extract or
runtime prompt path (hard rule). See `app/tools/textlayer.py` for the
extraction + sidecar caching logic.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from app.auth.deps import bind_workspace, current_ws

from app.api.routes._safety import safe_filename, safe_slug
from app.config import get_settings
from app.tools.textlayer import extract_textlayer


router = APIRouter(dependencies=[Depends(bind_workspace)])


@router.get("/lab/projects/{slug}/docs/by-name/{filename:path}/textlayer")
async def get_textlayer(slug: str, filename: str, page: int = 1) -> dict:
    """Return `{filename, page, page_w, page_h, image_w, image_h, scanned,
    spans[]}` for one page. PDF pages emit fitz vector spans; image / scanned
    pages emit `spans=[]` with `scanned=true` so the frontend can degrade
    gracefully (no overlay → user perceives "cannot select" → knows it's a
    scan)."""
    safe_slug(slug)
    safe_filename(filename)
    settings = get_settings()
    try:
        return await extract_textlayer(
            current_ws(), slug, filename, page=page,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="doc_not_found") from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
