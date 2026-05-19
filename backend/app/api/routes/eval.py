import json

from fastapi import APIRouter, HTTPException

from app.api.routes._safety import safe_slug
from app.config import get_settings
from app.schemas.score import ScoreResult
from app.tools.score import run_eval
from app.workspace.paths import metrics_dir, project_json_path


router = APIRouter()


@router.post("/lab/projects/{slug}/eval")
async def post_eval(slug: str) -> dict:
    from app.tools.schema import read_schema
    safe_slug(slug)
    settings = get_settings()
    ws = settings.workspace_root
    if not project_json_path(ws, slug).exists():
        raise HTTPException(status_code=404, detail="project_not_found")
    fields = await read_schema(ws, slug)
    if not fields:
        raise HTTPException(status_code=404, detail="schema_not_found")
    result = await run_eval(ws, slug)
    return result.model_dump(mode="json")


@router.post("/lab/projects/{slug}/score")
async def post_score(slug: str) -> dict:
    """M11 Phase B T10 — HTTP mirror of the `score` tool surface.

    Differs from `POST /lab/projects/{slug}/eval` only in error envelope
    shape: `eval` returns a bare `{"detail": "project_not_found"}` for
    legacy reasons; `score` returns the structured
    `{error_code, error_message_en}` shape every newer route uses. Both
    delegate to `run_eval` so the on-disk side effects
    (`metrics/eval_*.json` snapshot, per-field counts) are identical."""
    from app.tools.schema import read_schema
    safe_slug(slug)
    settings = get_settings()
    ws = settings.workspace_root
    if not project_json_path(ws, slug).exists():
        raise HTTPException(
            status_code=404,
            detail={"error_code": "project_not_found"},
        )
    fields = await read_schema(ws, slug)
    if not fields:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "schema_not_found"},
        )
    result = await run_eval(ws, slug)
    return result.model_dump(mode="json")


@router.get("/lab/projects/{slug}/evals/latest")
async def get_eval_latest(slug: str) -> dict:
    """Return the most-recent persisted `metrics/eval_*.json`.

    Filenames are `eval_YYYY-MM-DDTHH-MM-SSZ.json` → lex-sort == time-sort.
    Returns 404 with `eval_not_found` when the metrics dir is empty/missing
    so the frontend can render an "no eval yet" empty state instead of an error.
    """
    safe_slug(slug)
    settings = get_settings()
    if not project_json_path(settings.workspace_root, slug).exists():
        raise HTTPException(status_code=404, detail="project_not_found")
    md = metrics_dir(settings.workspace_root, slug)
    if not md.exists():
        raise HTTPException(status_code=404, detail="eval_not_found")
    candidates = sorted(md.glob("eval_*.json"))
    if not candidates:
        raise HTTPException(status_code=404, detail="eval_not_found")
    blob = json.loads(candidates[-1].read_text())
    return ScoreResult(**blob).model_dump(mode="json")
