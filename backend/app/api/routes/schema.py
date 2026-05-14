from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app.api.routes._safety import safe_job_id, safe_slug
from app.config import get_settings
from app.schemas.schema_field import SchemaField
from app.tools.schema import StructuralChangeError, write_schema
from app.workspace.paths import candidate_turn_path, parse_version_id, version_path


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
    return {"ok": True, "rationale": blob.get("rationale", "")}


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
    parsed = [f.model_dump(mode="json") for f in fields]
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
