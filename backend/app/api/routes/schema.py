from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app.api.routes._safety import safe_job_id, safe_project_id
from app.config import get_settings
from app.schemas.schema_field import SchemaField
from app.tools.schema import StructuralChangeError, write_schema
from app.workspace.paths import candidate_turn_path, parse_version_id, schema_path, version_path


router = APIRouter()


class AcceptBody(BaseModel):
    job_id: str
    turn: int


@router.post("/lab/projects/{project_id}/schema/accept-candidate")
async def accept_candidate(project_id: str, body: AcceptBody) -> dict:
    safe_project_id(project_id)
    safe_job_id(body.job_id)
    settings = get_settings()
    cp = candidate_turn_path(settings.workspace_root, project_id, body.job_id, body.turn)
    if not cp.exists():
        raise HTTPException(status_code=404, detail={"error_code": "candidate_not_found"})
    blob = json.loads(cp.read_text())
    fields_blob = blob.get("schema") or []
    fields = [SchemaField(**f) for f in fields_blob]
    try:
        await write_schema(
            settings.workspace_root, project_id, fields,
            reason=f"accept candidate j={body.job_id} turn={body.turn}",
            allow_structural=False,
        )
    except StructuralChangeError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "structural_change_in_candidate", "error_message_en": str(exc)},
        )
    return {"ok": True, "rationale": blob.get("rationale", "")}


@router.get("/lab/projects/{project_id}/schema/raw", response_class=PlainTextResponse)
async def get_project_schema_raw(project_id: str) -> PlainTextResponse:
    safe_project_id(project_id)
    settings = get_settings()
    sp = schema_path(settings.workspace_root, project_id)
    if not sp.exists():
        raise HTTPException(
            status_code=404,
            detail={"error_code": "schema_not_found"},
        )
    parsed = json.loads(sp.read_text())
    pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
    return PlainTextResponse(pretty, media_type="text/plain; charset=utf-8")


@router.get("/lab/projects/{project_id}/versions/{version_id}/raw")
async def get_project_version_raw(
    project_id: str,
    version_id: str,
    shape: str | None = Query(default=None),
):
    safe_project_id(project_id)
    n = parse_version_id(version_id)
    if n is None:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "invalid_version_id"},
        )
    settings = get_settings()
    vp = version_path(settings.workspace_root, project_id, n)
    if not vp.exists():
        raise HTTPException(
            status_code=404,
            detail={"error_code": "version_not_found"},
        )
    parsed = json.loads(vp.read_text())
    if shape == "fields":
        # passthrough: the frozen file is the source of truth; the Fields tab
        # consumes `fields[]` directly and ignores extra keys it doesn't know.
        return parsed
    pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
    return PlainTextResponse(pretty, media_type="text/plain; charset=utf-8")
