"""Lab-side HTTP for single-doc extract (M11 Phase B T10).

Mirrors the `extract_one` tool surface so a CLI agent driving HTTP can run
single extractions without going through chat. Distinct from the prod
fast-path `POST /v1/extract` in `publish.py`:

* Prod path takes a `published_id` form field, gates on `X-API-Key`, reads
  the *frozen* artifact at `_published/{pub_xxx}.json` (so its schema /
  model / params survive project rename or delete).
* Lab path is slug-scoped, uses session auth (none in dev — same as the
  rest of `/lab/*`), and runs through the project's *lab* state
  (active prompt's schema, active model). It writes back to
  `predictions/_draft/` exactly like the tool wrapper does.

Sharing the codepath: both ultimately reach `app.tools.extract`. The lab
route calls `extract_one` (which reads project state and persists the
draft prediction); the prod route calls `extract_bytes_with_schema` with
the frozen schema and no on-disk write. Different entry points, same
provider plumbing.

Batch extraction is intentionally not a dedicated endpoint — callers loop
this route in parallel (or, from chat, the agent emits parallel
`extract_one` tool_use blocks). One tool/route per logical op keeps the
progress surface uniform: every in-flight extraction is its own tool_call
event the UI can render and the API key can rate-limit individually.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.routes._safety import safe_filename, safe_slug
from app.config import get_settings
from app.tools.extract import extract_one
from app.workspace.paths import project_json_path


router = APIRouter()


def _project_or_404(slug: str) -> Path:
    safe_slug(slug)
    settings = get_settings()
    if not project_json_path(settings.workspace_root, slug).exists():
        raise HTTPException(
            status_code=404,
            detail={"error_code": "project_not_found"},
        )
    return settings.workspace_root


class _ExtractOneBody(BaseModel):
    """HTTP mirror of the `extract_one` tool input.

    `filename` is the on-disk doc handle (the only doc identifier post slug
    transparency). `prompt_id` / `model_id` are reserved hooks: the tool
    wrapper resolves both from the project's active state today, so we
    accept them for forward-compat but only `model_id` is plumbed through
    (the underlying `extract_one` takes an optional `model_id` already).
    A non-null `prompt_id` is currently a no-op and surfaces a 400 so
    callers don't silently assume per-call prompt switching is wired."""
    filename: str
    prompt_id: str | None = None
    model_id: str | None = None


@router.post("/lab/projects/{slug}/extract")
async def post_extract_one(slug: str, body: _ExtractOneBody) -> dict:
    """Extract a single document via the lab fast-path.

    Returns the prediction payload (`{entities: [...], _evidence: {...}}`)
    exactly as `extract_one` produces it — and as a side-effect persists
    the same payload to `predictions/_draft/{filename}.json` (so a follow-
    up `GET /lab/projects/{slug}/predictions/{filename}` reads the same
    blob without re-calling the model).

    Errors surface as structured 4xx envelopes:
    * 404 `project_not_found` — slug doesn't exist
    * 400 `invalid_filename` / `invalid_arg` — body validation
    * 400 `prompt_override_unsupported` — `prompt_id` is reserved
    * 404 `extract_failed` upstream errors bubble through unchanged
    """
    workspace = _project_or_404(slug)
    safe_filename(body.filename)
    if body.prompt_id is not None:
        # The tool surface doesn't expose per-call prompt override either —
        # callers should `switch_active_prompt` first. Surfacing this as
        # 400 keeps the wire contract honest.
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "prompt_override_unsupported",
                "error_message_en": (
                    "per-call prompt_id override is not supported; use "
                    "PUT /lab/projects/{slug}/prompts/active to switch first"
                ),
            },
        )
    try:
        payload = await extract_one(
            workspace, slug, body.filename, model_id=body.model_id or None,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "doc_not_found", "error_message_en": str(exc)},
        )
    except ValueError as exc:
        # Empty schema, etc. — surface validation reason.
        raise HTTPException(
            status_code=400,
            detail={"error_code": "invalid_arg", "error_message_en": str(exc)},
        )
    return payload


