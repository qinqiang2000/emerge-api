from __future__ import annotations

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
) -> None:
    """Persist a corrected extraction as ground truth for a doc.

    Overwrites any existing reviewed file for the same (project, doc).
    """
    payload = Reviewed(entities=entities, source=source, notes=notes).model_dump(
        by_alias=True, exclude_none=True, mode="json"
    )
    async with project_lock(workspace, project_id):
        reviewed_dir(workspace, project_id).mkdir(parents=True, exist_ok=True)
        atomic_write_json(reviewed_path(workspace, project_id, doc_id), payload)
