from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from app.workspace.paths import prediction_draft_path


async def get_prediction(
    workspace: Path,
    project_id: str,
    filename: str,
) -> Optional[dict[str, Any]]:
    """Return the latest draft prediction for a doc (keyed by filename), or None."""
    p = prediction_draft_path(workspace, project_id, filename)
    if not p.exists():
        return None
    return json.loads(p.read_text())
