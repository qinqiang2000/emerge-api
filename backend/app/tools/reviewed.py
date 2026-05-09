from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from app.schemas.reviewed import Reviewed, ReviewedSource
from app.workspace.atomic import atomic_write_json
from app.workspace.lock import project_lock
from app.workspace.paths import reviewed_dir, reviewed_path


async def save_reviewed(
    workspace: Path,
    project_id: str,
    doc_id: str,
    *,
    entities: list[dict[str, Any]],
    source: ReviewedSource = ReviewedSource.MANUAL,
    notes: Optional[dict[str, str]] = None,
    evidence: Optional[list[dict[str, Optional[int]]]] = None,
) -> None:
    """Persist a corrected extraction as ground truth for a doc.

    Overwrites any existing reviewed file for the same (project, doc).
    """
    payload = Reviewed(entities=entities, source=source, notes=notes, evidence=evidence).model_dump(
        by_alias=True, exclude_none=True, mode="json"
    )
    async with project_lock(workspace, project_id):
        reviewed_dir(workspace, project_id).mkdir(parents=True, exist_ok=True)
        atomic_write_json(reviewed_path(workspace, project_id, doc_id), payload)


async def list_reviewed(workspace: Path, project_id: str) -> list[dict[str, Any]]:
    """List all reviewed examples for a project as `[{doc_id, entities, ...}]`."""
    rd = reviewed_dir(workspace, project_id)
    if not rd.exists():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(rd.glob("*.json")):
        blob = json.loads(p.read_text())
        out.append({"doc_id": p.stem, **blob})
    return out


async def get_reviewed(
    workspace: Path,
    project_id: str,
    doc_id: str,
) -> Optional[dict[str, Any]]:
    """Return the reviewed payload for a doc or None if not yet reviewed."""
    p = reviewed_path(workspace, project_id, doc_id)
    if not p.exists():
        return None
    return json.loads(p.read_text())
