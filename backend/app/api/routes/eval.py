import json

from fastapi import APIRouter, HTTPException

from app.api.routes._safety import safe_project_id
from app.config import get_settings
from app.schemas.score import ScoreResult
from app.tools.score import run_eval
from app.workspace.paths import metrics_dir, project_json_path


router = APIRouter()


@router.post("/lab/projects/{project_id}/eval")
async def post_eval(project_id: str) -> dict:
    from app.tools.schema import read_schema
    safe_project_id(project_id)
    settings = get_settings()
    ws = settings.workspace_root
    if not project_json_path(ws, project_id).exists():
        raise HTTPException(status_code=404, detail="project_not_found")
    fields = await read_schema(ws, project_id)
    if not fields:
        raise HTTPException(status_code=404, detail="schema_not_found")
    result = await run_eval(ws, project_id)
    return result.model_dump(mode="json")


@router.get("/lab/projects/{project_id}/evals/latest")
async def get_eval_latest(project_id: str) -> dict:
    """Return the most-recent persisted `metrics/eval_*.json`.

    Filenames are `eval_YYYY-MM-DDTHH-MM-SSZ.json` → lex-sort == time-sort.
    Returns 404 with `eval_not_found` when the metrics dir is empty/missing
    so the frontend can render an "no eval yet" empty state instead of an error.
    """
    safe_project_id(project_id)
    settings = get_settings()
    if not project_json_path(settings.workspace_root, project_id).exists():
        raise HTTPException(status_code=404, detail="project_not_found")
    md = metrics_dir(settings.workspace_root, project_id)
    if not md.exists():
        raise HTTPException(status_code=404, detail="eval_not_found")
    candidates = sorted(md.glob("eval_*.json"))
    if not candidates:
        raise HTTPException(status_code=404, detail="eval_not_found")
    blob = json.loads(candidates[-1].read_text())
    return ScoreResult(**blob).model_dump(mode="json")
