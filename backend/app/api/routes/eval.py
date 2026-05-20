from __future__ import annotations

import json
import re
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app.api.routes._safety import safe_slug
from app.config import get_settings
from app.eval.score import run_eval
from app.schemas.score import ScoreResultSummary
from app.workspace.paths import (
    eval_cells_path,
    eval_matrix_path,
    eval_summary_path,
    metrics_dir,
    metrics_path,
    project_json_path,
)


router = APIRouter()


_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z$|^latest$")


def _validate_ts(ts: str) -> None:
    if not _TS_RE.match(ts or ""):
        raise HTTPException(
            status_code=400, detail={"error_code": "invalid_ts"},
        )


class _EvalBody(BaseModel):
    use_llm_judge: bool = False


@router.post("/lab/projects/{slug}/eval")
async def post_eval(slug: str, body: Optional[_EvalBody] = None) -> dict:
    from app.tools.schema import read_schema

    safe_slug(slug)
    settings = get_settings()
    ws = settings.workspace_root
    if not project_json_path(ws, slug).exists():
        raise HTTPException(status_code=404, detail="project_not_found")
    fields = await read_schema(ws, slug)
    if not fields:
        raise HTTPException(status_code=404, detail="schema_not_found")
    result = await run_eval(
        ws, slug,
        use_llm_judge=(body.use_llm_judge if body is not None else False),
    )
    return result.model_dump(mode="json")


@router.post("/lab/projects/{slug}/score")
async def post_score(slug: str, body: Optional[_EvalBody] = None) -> dict:
    """M11 Phase B T10 — HTTP mirror of the `score` tool surface. Differs from
    `POST /lab/projects/{slug}/eval` only in error envelope shape."""
    from app.tools.schema import read_schema

    safe_slug(slug)
    settings = get_settings()
    ws = settings.workspace_root
    if not project_json_path(ws, slug).exists():
        raise HTTPException(
            status_code=404, detail={"error_code": "project_not_found"},
        )
    fields = await read_schema(ws, slug)
    if not fields:
        raise HTTPException(
            status_code=404, detail={"error_code": "schema_not_found"},
        )
    result = await run_eval(
        ws, slug,
        use_llm_judge=(body.use_llm_judge if body is not None else False),
    )
    return result.model_dump(mode="json")


@router.get("/lab/projects/{slug}/evals")
async def list_evals(slug: str) -> list[dict]:
    """List all eval ts'es with meta + summary header. New dir-form preferred;
    legacy `eval_*.json` files are surfaced too (with `meta.legacy=True`)."""
    safe_slug(slug)
    settings = get_settings()
    if not project_json_path(settings.workspace_root, slug).exists():
        raise HTTPException(status_code=404, detail="project_not_found")
    md = metrics_dir(settings.workspace_root, slug)
    out: list[dict] = []
    if not md.exists():
        return out
    for child in sorted(md.iterdir(), reverse=True):
        if child.is_dir() and child.name.startswith("eval_"):
            ts = child.name[len("eval_"):]
            try:
                meta = json.loads((child / "meta.json").read_text())
                summary = json.loads((child / "summary.json").read_text())
                out.append({
                    "ts": ts,
                    "meta": meta,
                    "doc_accuracy": summary.get("doc_accuracy"),
                    "macro_f1": summary.get("macro_f1"),
                    "n_reviewed": summary.get("n_reviewed"),
                })
            except (FileNotFoundError, json.JSONDecodeError):
                continue
        elif (
            child.is_file()
            and child.name.startswith("eval_")
            and child.suffix == ".json"
        ):
            ts = child.stem[len("eval_"):]
            try:
                blob = json.loads(child.read_text())
                out.append({
                    "ts": ts,
                    "meta": {"legacy": True},
                    "doc_accuracy": None,
                    "macro_f1": blob.get("macro_f1"),
                    "n_reviewed": blob.get("n_reviewed"),
                })
            except json.JSONDecodeError:
                continue
    return out


@router.get("/lab/projects/{slug}/evals/latest")
async def get_eval_latest(slug: str) -> dict:
    """Return the most-recent persisted eval summary. Prefers the new dir
    artifact; falls back to legacy `eval_*.json` when only those exist."""
    safe_slug(slug)
    settings = get_settings()
    if not project_json_path(settings.workspace_root, slug).exists():
        raise HTTPException(status_code=404, detail="project_not_found")
    md = metrics_dir(settings.workspace_root, slug)
    if not md.exists():
        raise HTTPException(status_code=404, detail="eval_not_found")
    dirs = sorted(
        p for p in md.iterdir() if p.is_dir() and p.name.startswith("eval_")
    )
    if dirs:
        summary_p = dirs[-1] / "summary.json"
        if summary_p.exists():
            return json.loads(summary_p.read_text())
    files = sorted(md.glob("eval_*.json"))
    if files:
        blob = json.loads(files[-1].read_text())
        return ScoreResultSummary(**blob).model_dump(mode="json")
    raise HTTPException(status_code=404, detail="eval_not_found")


@router.get("/lab/projects/{slug}/eval/{ts}/summary.json")
async def get_eval_summary(slug: str, ts: str) -> dict:
    safe_slug(slug)
    _validate_ts(ts)
    settings = get_settings()
    p = eval_summary_path(settings.workspace_root, slug, ts)
    if not p.exists():
        legacy = metrics_path(settings.workspace_root, slug, f"eval_{ts}")
        if legacy.exists():
            return ScoreResultSummary(
                **json.loads(legacy.read_text())
            ).model_dump(mode="json")
        raise HTTPException(
            status_code=404, detail={"error_code": "eval_not_found"},
        )
    return json.loads(p.read_text())


@router.get("/lab/projects/{slug}/eval/{ts}/cells.jsonl")
async def get_eval_cells(slug: str, ts: str) -> PlainTextResponse:
    safe_slug(slug)
    _validate_ts(ts)
    settings = get_settings()
    p = eval_cells_path(settings.workspace_root, slug, ts)
    if not p.exists():
        raise HTTPException(
            status_code=404, detail={"error_code": "eval_cells_not_found"},
        )
    return PlainTextResponse(p.read_text(), media_type="application/x-ndjson")


@router.get("/lab/projects/{slug}/eval/{ts}/matrix.csv")
async def get_eval_matrix(slug: str, ts: str) -> PlainTextResponse:
    safe_slug(slug)
    _validate_ts(ts)
    settings = get_settings()
    p = eval_matrix_path(settings.workspace_root, slug, ts)
    if not p.exists():
        raise HTTPException(
            status_code=404, detail={"error_code": "eval_matrix_not_found"},
        )
    return PlainTextResponse(
        p.read_text(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="eval_{ts}.csv"',
        },
    )
