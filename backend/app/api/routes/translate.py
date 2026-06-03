"""HTTP route for per-page document translation.

Thin-delegate mirror of the `translate_page` MCP tool so the frontend
review overlay (and any CLI client) can drive both translate branches —
textlayer for electronic PDFs, vision for scanned / image docs — over plain
HTTP.

Translate is review UX only; bbox + lines NEVER reach the extract or
runtime prompt path (hard rule). See `app/tools/translate.py` for the
mode-selection + sidecar caching logic.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from app.auth.deps import bind_workspace, current_ws

from app.api.routes._safety import safe_filename, safe_slug
from app.config import get_settings
from app.tools.translate import translate_page


router = APIRouter(dependencies=[Depends(bind_workspace)])


@router.post("/lab/projects/{slug}/docs/by-name/{filename:path}/translate")
async def post_translate(
    slug: str,
    filename: str,
    page: int = Query(..., ge=1),
    lang: str = Query("zh"),
    force: bool = Query(False),
) -> dict:
    """Return `{mode, page_w, page_h, image_w, image_h, lines[], model_id,
    input_tokens, output_tokens, …}` for one page.

    Query params:
        page  — 1-indexed page number (required, ≥1)
        lang  — target language code; default `zh` (= 简体中文)
        force — bypass the sidecar cache (Shift+T from the frontend)

    Errors:
        404 `doc_not_found`            — missing doc sidecar
        400 (with detail message)      — page out of range / length mismatch
        502 `translate_provider_failed` — provider call raised after retries
    """
    safe_slug(slug)
    safe_filename(filename)
    settings = get_settings()
    try:
        return await translate_page(
            current_ws(), slug, filename,
            page=page, target_lang=lang, force_refresh=force,
        )
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "doc_not_found", "error_message_en": str(e)},
        ) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail={
                "error_code": "translate_provider_failed",
                "error_message_en": str(e),
            },
        ) from e
