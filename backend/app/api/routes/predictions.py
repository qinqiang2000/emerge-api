from fastapi import APIRouter, Depends, HTTPException
from app.auth.deps import bind_workspace, current_ws

from app.api.routes._safety import safe_filename, safe_slug
from app.config import get_settings
from app.tools.predictions import get_prediction


router = APIRouter(dependencies=[Depends(bind_workspace)])


@router.get("/lab/projects/{slug}/predictions/{filename:path}")
async def get_doc_prediction(slug: str, filename: str) -> dict:
    """Fetch the latest draft prediction for a doc. `filename` is the on-disk
    name (the only doc handle)."""
    safe_slug(slug)
    safe_filename(filename)
    settings = get_settings()
    payload = await get_prediction(current_ws(), slug, filename)
    if payload is None:
        raise HTTPException(status_code=404, detail="prediction_not_found")
    return payload
