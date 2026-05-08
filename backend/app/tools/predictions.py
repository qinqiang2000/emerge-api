from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from app.workspace.paths import predictions_draft_dir


async def get_prediction(
    workspace: Path,
    project_id: str,
    doc_id: str,
) -> Optional[dict[str, Any]]:
    """Return the latest draft prediction for a doc, or None."""
    p = predictions_draft_dir(workspace, project_id) / f"{doc_id}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())
