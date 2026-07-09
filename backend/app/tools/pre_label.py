"""Pro Labeler — `label_docs` writes pre-label drafts produced by a stronger LLM.

The "pro old-timer" model (e.g. `gemini-pro-latest`) drafts labels into
`reviewed/_pending/{filename}.json`. The human boss then verifies in Review
mode and saves; `save_reviewed` atomically deletes the matching pending file
inside the same `project_lock`.

`label_docs` is an *atomic small-batch* tool. The `pre_label_runner` subagent
(see `app/skills/emerge_pre_label_runner.md`) loops over `label_docs` calls
in chunks of ≤10, narrating progress between batches; idempotent
`_pending/` skip makes the loop safely resumable after a disconnect or cancel.

Hard rule: pending files are **opaque** to `score()`, `/improve`,
`/publish`, `readiness_check` — those paths glob `reviewed/*.json` and the
`_pending/` subdir is naturally excluded. The only paths that see pending
are Review mode (banner + form prefill) and `save_reviewed` (cleanup).

Pre-label is NOT a substitute for `extract` — its output is awaiting human
verification, not "what production would emit". Pre-label is NOT a promoter
either — only `save_reviewed` (i.e. the boss clicking Save) promotes a draft
to ground truth.

Module is named `pre_label.py` for historical reasons; the public entrypoint
is `label_docs`.
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
from app.tools.prompt import read_active_prompt
from app.tools.schema import doc_to_blocks
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


def _read_project_labeler_override(workspace: Path, slug: str) -> str | None:
    """Return `project.json.labeler_model` if explicitly set, else None.

    Missing file / unparseable JSON / missing key / null value all collapse
    to None (= "no override; use env default").
    """
    pj = project_json_path(workspace, slug)
    if not pj.exists():
        return None
    try:
        blob = json.loads(pj.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return blob.get("labeler_model") or None


async def get_labeler_config(workspace: Path, slug: str) -> dict[str, Any]:
    """Project-level labeler config snapshot — what `label_docs` will resolve to.

    Exists so the agent can answer "what labeler will run?" without `Read`ing
    `project.json` and missing the env fallback. Returns:

        override:    project.json.labeler_model (None if unset)
        env_default: EMERGE_DEFAULT_LABELER_MODEL (None if unset)
        resolved:    what label_docs will actually call (None = unconfigured)
        source:      "override" | "env_default" | "unconfigured"

    See [[feedback_ai_native_api_symmetry]] — every lab decision the UI exposes
    must also be inspectable through tools.
    """
    override = _read_project_labeler_override(workspace, slug)
    env_default = get_settings().default_labeler_model or None
    if override:
        resolved, source = override, "override"
    elif env_default:
        resolved, source = env_default, "env_default"
    else:
        resolved, source = None, "unconfigured"
    return {
        "override": override,
        "env_default": env_default,
        "resolved": resolved,
        "source": source,
    }


async def _resolve_labeler_model(
    workspace: Path, slug: str, override: str | None,
) -> str:
    """Priority: call-arg > project.json.labeler_model > settings default.

    `project.json.labeler_model` is normally null — `init_project` no longer
    freezes the env default into it; only `set_labeler_model` writes here when
    the user explicitly overrides. Updating `.env` then "just works" for
    every project that hasn't been explicitly overridden.
    """
    if override:
        return override
    project_override = _read_project_labeler_override(workspace, slug)
    if project_override:
        return project_override
    settings = get_settings()
    if settings.default_labeler_model:
        return settings.default_labeler_model
    raise LabelerNotConfiguredError("labeler_model not configured")


async def label_docs(
    workspace: Path,
    slug: str,
    *,
    filenames: list[str] | None = None,
    labeler_model: str | None = None,
    provider: Provider | None = None,
) -> dict[str, Any]:
    """Pro-labeler synchronous batch.

    - Skips docs that already have `reviewed/` (human-verified ground truth wins).
    - **Idempotent skip**: also skips docs whose `_pending/` draft already
      exists. This is what makes the subagent runner safely resumable — a
      fresh tool call after a SDK disconnect / cancel sees prior batches'
      pending files and no-ops them, so a re-issued chunk doesn't re-spend
      LLM tokens.
    - `filenames=None` defaults to all docs without a `reviewed/` entry.

    Returns `{processed, skipped, errors, labeler_model}`. Errors per doc are
    soft — the batch keeps going.
    """
    await migrate_project_if_needed(workspace, slug)
    # Resolve labeler first so an unconfigured project gets the canonical
    # `labeler_model_not_configured` error (HTTP 400 in the route) rather than
    # a vague "empty schema" — labeler config is the more fundamental signal.
    mid = await _resolve_labeler_model(workspace, slug, labeler_model)
    pv = await read_active_prompt(workspace, slug)
    schema = pv.schema
    if not schema:
        raise ValueError("project has empty schema; nothing to pre-label")

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
    global_notes = pv.global_notes

    for fn in filenames:
        if reviewed_path(workspace, slug, fn).exists():
            skipped.append({"filename": fn, "reason": "already_reviewed"})
            continue
        if pending_reviewed_path(workspace, slug, fn).exists():
            skipped.append({"filename": fn, "reason": "already_pending"})
            continue
        try:
            doc_blocks = await doc_to_blocks(
                workspace, slug, fn, supports_pdf=provider.supports_pdf,
            )
            user_blocks: list[ContentBlock] = (
                [TextBlock(text=global_notes)] if global_notes else []
            ) + [TextBlock(text=field_instructions)] + doc_blocks
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
            # M14 — stamp the pending blob with kind="pre_label". The prompt
            # axis is the active prompt (used to build label instructions);
            # the model axis is the resolved labeler model (`mid`), passed via
            # `extract_model_override` since there's no project ModelConfig
            # behind the labeler — it resolves from env / project override
            # without going through models/{m_*}.json.
            from app.eval.run_stamp import build_stamp

            stamp = build_stamp(
                "pre_label", None, pv, extract_model_override=mid,
            )
            payload["_run"] = stamp.model_dump(mode="json", exclude_none=False)
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
                "error_code": "label_docs_failed",
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
