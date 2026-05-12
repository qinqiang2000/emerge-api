import json

from fastapi import APIRouter, HTTPException

from app.api.routes._safety import safe_project_id
from app.config import get_settings
from app.tools.docs import list_docs
from app.tools.projects import list_projects
from app.tools.reviewed import list_reviewed
from app.workspace.paths import predictions_draft_dir, project_json_path


router = APIRouter()


@router.get("/lab/projects")
async def get_projects() -> list[dict]:
    settings = get_settings()
    return await list_projects(settings.workspace_root)


@router.get("/lab/projects/{project_id}")
async def get_project(project_id: str) -> dict:
    safe_project_id(project_id)
    settings = get_settings()
    from app.workspace.migrate import migrate_project_if_needed

    pj = project_json_path(settings.workspace_root, project_id)
    if not pj.exists():
        raise HTTPException(status_code=404, detail="project_not_found")
    await migrate_project_if_needed(settings.workspace_root, project_id)
    blob = json.loads(pj.read_text())
    return {"project_id": project_id, **blob}


@router.get("/lab/projects/{project_id}/docs")
async def get_project_docs(project_id: str) -> list[dict]:
    safe_project_id(project_id)
    settings = get_settings()
    docs = await list_docs(settings.workspace_root, project_id)
    reviewed_ids = {
        r["doc_id"] for r in await list_reviewed(settings.workspace_root, project_id)
    }
    pdir = predictions_draft_dir(settings.workspace_root, project_id)
    pred_ids = {p.stem for p in pdir.glob("*.json")} if pdir.exists() else set()
    out = []
    for d in docs:
        out.append({
            **d,
            "has_reviewed": d["doc_id"] in reviewed_ids,
            "has_prediction": d["doc_id"] in pred_ids,
        })
    return out


@router.get("/lab/projects/{project_id}/schema")
async def get_project_schema(project_id: str) -> list[dict]:
    safe_project_id(project_id)
    settings = get_settings()
    from app.tools.schema import read_schema
    from app.workspace.migrate import migrate_project_if_needed

    pj = project_json_path(settings.workspace_root, project_id)
    if not pj.exists():
        raise HTTPException(status_code=404, detail="schema_not_found")
    await migrate_project_if_needed(settings.workspace_root, project_id)
    fields = await read_schema(settings.workspace_root, project_id)
    return [f.model_dump(mode="json") for f in fields]
