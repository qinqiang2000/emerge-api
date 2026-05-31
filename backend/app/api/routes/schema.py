from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.api.routes._safety import safe_chat_id, safe_filename, safe_job_id, safe_slug
from app.config import get_settings
from app.schemas.reviewed import NoteConsumption, ReviewedSource
from app.schemas.schema_field import SchemaField
from app.tools.reviewed import get_reviewed, save_reviewed
from app.tools.schema import (
    SchemaImportError,
    StructuralChangeError,
    derive_schema,
    import_schema_from_yaml,
    write_schema,
)
from app.workspace.paths import candidate_turn_path, parse_version_id, project_json_path, version_path


log = logging.getLogger(__name__)


router = APIRouter()


class AcceptBody(BaseModel):
    job_id: str
    turn: int


@router.post("/lab/projects/{slug}/schema/accept-candidate")
async def accept_candidate(slug: str, body: AcceptBody) -> dict:
    safe_slug(slug)
    safe_job_id(body.job_id)
    settings = get_settings()
    cp = candidate_turn_path(settings.workspace_root, slug, body.job_id, body.turn)
    if not cp.exists():
        raise HTTPException(status_code=404, detail={"error_code": "candidate_not_found"})
    blob = json.loads(cp.read_text())
    fields_blob = blob.get("schema") or []
    fields = [SchemaField(**f) for f in fields_blob]
    try:
        await write_schema(
            settings.workspace_root, slug, fields,
            reason=f"accept candidate j={body.job_id} turn={body.turn}",
            allow_structural=False,
        )
    except StructuralChangeError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "structural_change_in_candidate", "error_message_en": str(exc)},
        )

    # Phase B: write `_notes_consumed` entries for the reviewed files whose
    # inline notes drove this candidate's description changes. `notes_hit`
    # was already sanity-filtered by the proposer pipeline, but we still
    # gate per-field on the reviewed file actually having that note in
    # `_notes` (defensive against any candidate JSON that got hand-edited or
    # came from an older code path).
    consumed_summary = await _mark_notes_consumed(
        workspace=settings.workspace_root,
        slug=slug,
        notes_hit=blob.get("notes_hit") or [],
        job_id=body.job_id,
        turn=body.turn,
    )
    out: dict = {"ok": True, "rationale": blob.get("rationale", "")}
    if consumed_summary:
        out["notes_consumed"] = consumed_summary
    return out


async def _mark_notes_consumed(
    *,
    workspace,
    slug: str,
    notes_hit: list,
    job_id: str,
    turn: int,
) -> dict[str, list[str]]:
    """Best-effort: for each validated `<filename>.<field>` hit, write a
    `_notes_consumed[field]` entry on the matching reviewed file.

    Wrapped in per-file try/except so one bad reviewed file doesn't fail the
    whole accept. Returns a `{filename: [fields_consumed]}` map for the
    response payload so callers can confirm what was written.
    """
    if not notes_hit:
        return {}
    # Group hits by filename. Split on the LAST dot because filenames
    # legitimately contain dots (e.g. `inv-042.pdf.buyer_name` reads as
    # filename `inv-042.pdf` + field `buyer_name`); SchemaField names are
    # letter-led identifiers with no dot.
    grouped: dict[str, list[str]] = {}
    for hit in notes_hit:
        if not isinstance(hit, str) or "." not in hit:
            continue
        filename, _, field = hit.rpartition(".")
        if filename and field:
            grouped.setdefault(filename, []).append(field)
    if not grouped:
        return {}

    # Read the project's active prompt id so the consumption record is
    # anchored to the prompt that just changed. (publish bumps versions; the
    # prompt is the right runtime anchor.)
    active_prompt_id = ""
    try:
        proj = json.loads(project_json_path(workspace, slug).read_text())
        active_prompt_id = str(proj.get("active_prompt_id") or "")
    except (OSError, json.JSONDecodeError):
        pass

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    source_ref = f"{job_id}.turn_{turn}"
    consumed_summary: dict[str, list[str]] = {}

    for filename, fields in grouped.items():
        try:
            existing = await get_reviewed(workspace, slug, filename)
            if not existing:
                # No reviewed file for this hit → skip silently. Should be
                # unreachable since proposer notes_hit are filtered against
                # reviewed_dict, but defensive.
                continue
            notes_map = existing.get("_notes") or {}
            existing_consumed_raw = existing.get("_notes_consumed") or {}
            # Re-parse existing consumed map into NoteConsumption to merge
            # cleanly; preserve everything already there.
            consumed: dict[str, NoteConsumption] = {}
            if isinstance(existing_consumed_raw, dict):
                for k, v in existing_consumed_raw.items():
                    try:
                        consumed[k] = NoteConsumption(**v)
                    except Exception:  # noqa: BLE001
                        # Malformed prior entry — skip rather than fail.
                        continue
            consumed_this_file: list[str] = []
            for field in fields:
                # Defensive: only mark consumption when the field truly has
                # an inline note. Prevents `notes_hit` referring to a field
                # that exists in the schema but had no user note from
                # writing a phantom audit record.
                if field not in notes_map:
                    continue
                consumed[field] = NoteConsumption(
                    consumed_at=now_iso,
                    consumed_via="accept_candidate",
                    source_ref=source_ref,
                    active_prompt_id=active_prompt_id,
                )
                consumed_this_file.append(field)
            if not consumed_this_file:
                continue
            # Re-persist with merged consumed map. Keep entities / notes /
            # evidence intact (read-modify-write). save_reviewed's
            # defensive merge would also preserve the existing map if we
            # omitted notes_consumed entirely; here we explicitly pass the
            # merged map to add the new entries.
            await save_reviewed(
                workspace,
                slug,
                filename,
                entities=existing.get("entities") or [],
                source=ReviewedSource(existing.get("source", "manual")),
                notes=notes_map or None,
                evidence=existing.get("_evidence"),
                notes_consumed={k: v.model_dump(mode="json") for k, v in consumed.items()},
            )
            consumed_summary[filename] = consumed_this_file
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "accept_candidate: failed to mark notes_consumed for %s/%s: %s",
                slug, filename, exc,
            )
            continue
    return consumed_summary


class _WriteSchemaBody(BaseModel):
    """HTTP mirror of the `write_schema` tool input.

    `schema` is a list of SchemaField-shaped dicts; we revalidate via the
    pydantic model so bad shapes 400 with a useful error before the tool
    function ever sees them. `reason` is currently audit-only (the tool
    accepts it for signature compat); `allow_structural` and `global_notes`
    follow the tool's semantics exactly."""

    fields: list[dict[str, Any]] = Field(alias="schema")
    reason: str
    allow_structural: bool = False
    global_notes: str | None = None

    model_config = {"populate_by_name": True}


@router.post("/lab/projects/{slug}/schema")
async def post_write_schema(slug: str, body: _WriteSchemaBody) -> dict:
    """Replace the active prompt's schema (and optionally `global_notes`).
    Mirrors the `write_schema` tool surface so a CLI agent can call this
    over HTTP without going through chat (M11-T8). Returns `{ok: true}`;
    structural changes require `allow_structural=true` (the tool's
    `StructuralChangeError` gate is preserved).

    The body uses `schema` as the field key on the wire to keep the contract
    aligned with the tool; the pydantic model aliases it to `fields`
    internally so it doesn't shadow `BaseModel.schema`."""
    safe_slug(slug)
    settings = get_settings()
    try:
        fields = [SchemaField(**f) for f in body.fields]
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "invalid_schema",
                "error_message_en": str(exc),
            },
        )

    pj = project_json_path(settings.workspace_root, slug)
    if not pj.exists():
        raise HTTPException(
            status_code=404,
            detail={"error_code": "project_not_found"},
        )

    try:
        await write_schema(
            settings.workspace_root,
            slug,
            fields,
            reason=body.reason,
            allow_structural=body.allow_structural,
            global_notes=body.global_notes,
        )
    except StructuralChangeError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "structural_change_blocked",
                "error_message_en": str(exc),
            },
        )
    return {"ok": True}


class _DeriveSchemaBody(BaseModel):
    """HTTP mirror of the `derive_schema` tool input.

    `sample_filenames` and `intent` map 1:1 to the tool's required args.
    The provider/model are resolved from the project's active model — same
    as the tool wrapper — so callers don't need to pass them."""

    sample_filenames: list[str]
    intent: str


@router.post("/lab/projects/{slug}/schema/derive")
async def post_derive_schema(slug: str, body: _DeriveSchemaBody) -> dict:
    """Propose a schema from sample documents + user intent. Returns
    `{fields: [SchemaField, ...]}`. Does NOT persist — caller decides whether
    to follow up with `POST /lab/projects/{slug}/schema` to write. Mirrors
    the `derive_schema` tool (M11-T8); provider + model are picked off the
    project's active model exactly the way the tool wrapper does."""
    safe_slug(slug)
    settings = get_settings()
    pj = project_json_path(settings.workspace_root, slug)
    if not pj.exists():
        raise HTTPException(
            status_code=404,
            detail={"error_code": "project_not_found"},
        )

    from app.provider import get_provider_for_model
    from app.tools import model as model_mod

    mc = await model_mod.read_active_model(settings.workspace_root, slug)
    mid = mc.provider_model_id
    prj_provider = get_provider_for_model(mid, provider=mc.provider)
    fields = await derive_schema(
        settings.workspace_root,
        slug,
        sample_filenames=body.sample_filenames,
        intent=body.intent,
        provider=prj_provider,
        model_id=mid,
    )
    return {
        "fields": [f.model_dump(mode="json", exclude_none=True) for f in fields],
        "fields_proposed": len(fields),
    }


class _ImportSchemaFromYamlBody(BaseModel):
    """HTTP mirror of the `import_schema_from_yaml` tool input. The slug,
    chat_id, and filename are URL path components; this body carries the write
    toggles. `allow_structural` defaults `True` because import is inherently
    structural; pass `False` to surface the structural-change gate. Set
    `as_new_variant=True` to mint a new prompt variant instead of replacing the
    active prompt (active is left untouched; adopt via switch_active_prompt).
    `new_label` names that variant (defaults imported:<filename>)."""

    allow_structural: bool = True
    as_new_variant: bool = False
    new_label: str | None = None


@router.post("/lab/projects/{slug}/chats/{chat_id}/attachments/{filename:path}/import-schema")
async def post_import_schema_from_yaml(
    slug: str,
    chat_id: str,
    filename: str,
    body: _ImportSchemaFromYamlBody | None = None,
) -> dict[str, Any]:
    """Import a chat-attached yml/yaml/json file as the project's schema.

    Mirrors the `import_schema_from_yaml` tool surface so a CLI agent can
    drive schema imports over HTTP without going through chat. The body is
    optional — omit to use `allow_structural=true` (the tool's default).

    Returns `{ok: true, field_count, names: [...]}` on success.
    400 with `invalid_schema_yaml` (or another tool-side error_code) on
    parse / validation failure; 404 with `attachment_not_found` when the
    chat attachment is missing.
    """
    safe_slug(slug)
    safe_chat_id(chat_id)
    safe_filename(filename)
    settings = get_settings()
    pj = project_json_path(settings.workspace_root, slug)
    if not pj.exists():
        raise HTTPException(
            status_code=404,
            detail={"error_code": "project_not_found"},
        )
    allow_structural = bool(body.allow_structural) if body is not None else True
    as_new_variant = bool(body.as_new_variant) if body is not None else False
    new_label = body.new_label if body is not None else None
    try:
        out = await import_schema_from_yaml(
            settings.workspace_root,
            slug,
            chat_id,
            filename,
            allow_structural=allow_structural,
            as_new_variant=as_new_variant,
            new_label=new_label,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "attachment_not_found",
                "error_message_en": str(exc),
            },
        )
    except SchemaImportError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": exc.error_code,
                "error_message_en": exc.error_message_en,
            },
        )
    except StructuralChangeError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "structural_change_blocked",
                "error_message_en": str(exc),
            },
        )
    return out


@router.get("/lab/projects/{slug}/schema/raw", response_class=PlainTextResponse)
async def get_project_schema_raw(slug: str) -> PlainTextResponse:
    safe_slug(slug)
    settings = get_settings()
    from app.tools.schema import read_schema
    from app.workspace.migrate import migrate_project_if_needed
    from app.workspace.paths import project_json_path

    pj = project_json_path(settings.workspace_root, slug)
    if not pj.exists():
        raise HTTPException(
            status_code=404,
            detail={"error_code": "schema_not_found"},
        )
    await migrate_project_if_needed(settings.workspace_root, slug)
    fields = await read_schema(settings.workspace_root, slug)
    parsed = [f.model_dump(mode="json", exclude_none=True) for f in fields]
    pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
    return PlainTextResponse(pretty, media_type="text/plain; charset=utf-8")


@router.get("/lab/projects/{slug}/versions/{version_id}/raw")
async def get_project_version_raw(
    slug: str,
    version_id: str,
    shape: str | None = Query(default=None),
):
    safe_slug(slug)
    n = parse_version_id(version_id)
    if n is None:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "invalid_version_id"},
        )
    settings = get_settings()
    vp = version_path(settings.workspace_root, slug, n)
    if not vp.exists():
        raise HTTPException(
            status_code=404,
            detail={"error_code": "version_not_found"},
        )
    parsed = json.loads(vp.read_text())
    if shape == "fields":
        # Normalize to the spec §3.3 contract: { fields: SchemaField[], frozen_at, ... }.
        # publish.py writes the frozen blob with key `schema`; the Fields tab + the
        # spec both name the list `fields`, so we remap here as the wire-format adapter.
        # If a future frozen-blob writer ever emits `fields` directly, that key wins.
        out = {k: v for k, v in parsed.items() if k != "schema"}
        out["fields"] = parsed.get("fields", parsed.get("schema", []))
        return out
    pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
    return PlainTextResponse(pretty, media_type="text/plain; charset=utf-8")
