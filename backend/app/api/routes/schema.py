from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.routes._safety import safe_job_id, safe_project_id
from app.config import get_settings
from app.schemas.schema_field import SchemaField
from app.tools.schema import StructuralChangeError, write_schema
from app.workspace.paths import candidate_turn_path


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
