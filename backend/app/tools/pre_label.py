"""Pro Labeler — pre-label drafts produced by a stronger LLM.

The "pro old-timer" model (e.g. `gemini-pro-latest`) drafts labels into
`reviewed/_pending/{filename}.json`. The human boss then verifies in Review
mode and saves; `save_reviewed` atomically deletes the matching pending file
inside the same `project_lock`.

Hard rule: pending files are **opaque** to `score()`, `/improve`,
`/publish`, `readiness_check` — those paths glob `reviewed/*.json` and the
`_pending/` subdir is naturally excluded. The only paths that see pending
are Review mode (banner + form prefill) and `save_reviewed` (cleanup).

Pre-label is NOT a substitute for `extract` — its output is awaiting human
verification, not "what production would emit". Pre-label is NOT a promoter
either — only `save_reviewed` (i.e. the boss clicking Save) promotes a draft
to ground truth.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.provider import get_provider_for_model
from app.provider.base import ContentBlock, Provider, TextBlock
from app.schemas.extraction import ExtractionOutput
from app.tools.extract import (
    _EXTRACT_SYSTEM,
    _build_field_instructions,
    _build_response_schema,
)
from app.tools.schema import _doc_to_block, read_schema
from app.workspace.atomic import atomic_write_json
from app.workspace.lock import project_lock
from app.workspace.migrate import migrate_project_if_needed
from app.workspace.paths import (
    pending_reviewed_dir,
    pending_reviewed_path,
    project_json_path,
    reviewed_path,
)


class LabelerNotConfiguredError(ValueError):
    """Neither the call-arg override, `project.json.labeler_model`, nor the
    `EMERGE_DEFAULT_LABELER_MODEL` env default is set."""


async def _resolve_labeler_model(
    workspace: Path, slug: str, override: str | None,
) -> str:
    """Priority: call-arg > project.json.labeler_model > settings default."""
    if override:
        return override
    pj = project_json_path(workspace, slug)
    if pj.exists():
        try:
            blob = json.loads(pj.read_text())
        except (OSError, json.JSONDecodeError):
            blob = {}
        if blob.get("labeler_model"):
            return blob["labeler_model"]
    settings = get_settings()
    if settings.default_labeler_model:
        return settings.default_labeler_model
    raise LabelerNotConfiguredError("labeler_model not configured")


async def pre_label(
    workspace: Path,
    slug: str,
    *,
    filenames: list[str] | None = None,
    labeler_model: str | None = None,
    provider: Provider | None = None,
) -> dict[str, Any]:
    """Pro-labeler synchronous batch.

    - Skips docs that already have `reviewed/` (human-verified ground truth wins).
    - Overwrites existing pending (re-run with a different labeler model OK).
    - `filenames=None` defaults to all docs without a `reviewed/` entry.

    Returns `{processed, skipped, errors, labeler_model}`. Errors per doc are
    soft — the batch keeps going.
    """
    await migrate_project_if_needed(workspace, slug)
    schema = await read_schema(workspace, slug)
    if not schema:
        raise ValueError("project has empty schema; nothing to pre-label")

    mid = await _resolve_labeler_model(workspace, slug, labeler_model)
    if provider is None:
        provider = get_provider_for_model(mid)

    if filenames is None or len(filenames) == 0:
        from app.tools.docs import list_docs

        all_docs = await list_docs(workspace, slug)
        filenames = [d["filename"] for d in all_docs]

    processed: list[str] = []
    skipped: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []

    response_schema = _build_response_schema(schema)
    field_instructions = _build_field_instructions(schema)

    for fn in filenames:
        if reviewed_path(workspace, slug, fn).exists():
            skipped.append({"filename": fn, "reason": "already_reviewed"})
            continue
        try:
            user_blocks: list[ContentBlock] = [
                TextBlock(text=field_instructions),
                await _doc_to_block(workspace, slug, fn),
            ]
            result = await provider.extract(
                model_id=mid,
                system_prompt=_EXTRACT_SYSTEM,
                user_content=user_blocks,
                response_schema=response_schema,
            )
            output = ExtractionOutput(**result.raw_json)
            payload = output.model_dump(by_alias=True, exclude_none=True)
            payload["labeler_model"] = mid
            payload["created_at"] = datetime.now(timezone.utc).isoformat()
            async with project_lock(workspace, slug):
                pending_reviewed_dir(workspace, slug).mkdir(
                    parents=True, exist_ok=True,
                )
                atomic_write_json(
                    pending_reviewed_path(workspace, slug, fn), payload,
                )
            processed.append(fn)
        except Exception as e:  # noqa: BLE001
            errors.append({
                "filename": fn,
                "error_code": "pre_label_failed",
                "error_message_en": str(e),
            })

    return {
        "processed": processed,
        "skipped": skipped,
        "errors": errors,
        "labeler_model": mid,
    }


async def get_pending(
    workspace: Path, slug: str, filename: str,
) -> dict[str, Any] | None:
    """Return the pending draft for one doc, or None if nothing's drafted yet."""
    p = pending_reviewed_path(workspace, slug, filename)
    if not p.exists():
        return None
    return json.loads(p.read_text())


async def set_labeler_model(
    workspace: Path, slug: str, model_id: str,
) -> None:
    """Persist `project.json.labeler_model = model_id`. Used by the
    `set_labeler_model` MCP tool when the user says "换 pro 模型" / "用 X 当 pro"."""
    async with project_lock(workspace, slug):
        pj = project_json_path(workspace, slug)
        blob = json.loads(pj.read_text())
        blob["labeler_model"] = model_id
        atomic_write_json(pj, blob)
