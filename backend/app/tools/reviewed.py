from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from app.schemas.reviewed import NoteConsumption, Reviewed, ReviewedSource
from app.workspace.atomic import atomic_write_json
from app.workspace.lock import project_lock
from app.workspace.paths import reviewed_dir, reviewed_path


# Sentinel to distinguish "caller omitted notes_consumed" (preserve existing
# on-disk map) from "caller passed an explicit empty dict" (clear the map).
# Using a plain None as the omitted-marker means callers can never explicitly
# "clear" via None — they must pass {} to clear. This is documented behavior.
_OMITTED = object()


async def save_reviewed(
    workspace: Path,
    project_id: str,
    filename: str,
    *,
    entities: list[dict[str, Any]],
    source: ReviewedSource = ReviewedSource.MANUAL,
    notes: Optional[dict[str, str]] = None,
    evidence: Optional[list[dict[str, Optional[int]]]] = None,
    notes_consumed: Any = _OMITTED,
) -> None:
    """Persist a corrected extraction as ground truth for a doc.

    Overwrites any existing reviewed file for the same (project, filename).
    Reviewed files are keyed by the doc's on-disk filename — that's the only
    doc handle in this codebase.

    `notes_consumed` defensive merge semantics:
        - **omitted** (default sentinel) → if the on-disk file already has a
          `_notes_consumed` map, preserve it. Agent value-correction calls
          that don't round-trip the consumption metadata would otherwise
          silently clear the audit trail.
        - explicit `None` → treated the same as omitted (preserve).
        - explicit dict (including empty `{}`) → use as-is. Callers that
          genuinely want to clear must pass `{}`.

    `notes_consumed` accepts either `dict[str, NoteConsumption]` or
    `dict[str, dict[str, str]]` (raw kwargs from the MCP tool boundary).
    """
    # Resolve notes_consumed against the existing on-disk map.
    resolved_consumed: Optional[dict[str, NoteConsumption]]
    if notes_consumed is _OMITTED or notes_consumed is None:
        # Preserve any existing on-disk map.
        existing = await get_reviewed(workspace, project_id, filename)
        if existing and isinstance(existing.get("_notes_consumed"), dict):
            raw = existing["_notes_consumed"]
            resolved_consumed = {
                k: NoteConsumption(**v) if not isinstance(v, NoteConsumption) else v
                for k, v in raw.items()
            }
        else:
            resolved_consumed = None
    elif isinstance(notes_consumed, dict):
        if not notes_consumed:
            # Explicit empty dict → clear.
            resolved_consumed = None
        else:
            resolved_consumed = {
                k: NoteConsumption(**v) if not isinstance(v, NoteConsumption) else v
                for k, v in notes_consumed.items()
            }
    else:
        # Fallback: ignore garbage shapes.
        resolved_consumed = None

    payload = Reviewed(
        entities=entities,
        source=source,
        notes=notes,
        notes_consumed=resolved_consumed,
        evidence=evidence,
    ).model_dump(by_alias=True, exclude_none=True, mode="json")
    async with project_lock(workspace, project_id):
        reviewed_dir(workspace, project_id).mkdir(parents=True, exist_ok=True)
        atomic_write_json(reviewed_path(workspace, project_id, filename), payload)


async def list_reviewed(workspace: Path, project_id: str) -> list[dict[str, Any]]:
    """List all reviewed examples for a project as `[{filename, entities, ...}]`.

    `filename` is recovered from the on-disk JSON filename (which by
    construction matches the doc's on-disk filename). Note the file stem
    includes the doc's extension (e.g. `inv-001.pdf.json` → stem
    `inv-001.pdf`)."""
    rd = reviewed_dir(workspace, project_id)
    if not rd.exists():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(rd.glob("*.json")):
        blob = json.loads(p.read_text())
        # Strip the trailing `.json` to recover the original doc filename.
        out.append({"filename": p.name[:-len(".json")], **blob})
    return out


async def get_reviewed(
    workspace: Path,
    project_id: str,
    filename: str,
) -> Optional[dict[str, Any]]:
    """Return the reviewed payload for a doc or None if not yet reviewed."""
    p = reviewed_path(workspace, project_id, filename)
    if not p.exists():
        return None
    return json.loads(p.read_text())
