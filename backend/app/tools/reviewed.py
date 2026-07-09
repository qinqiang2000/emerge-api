from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from app.schemas.reviewed import NoteConsumption, Reviewed, ReviewedSource
from app.workspace.atomic import atomic_write_json
from app.workspace.lock import project_lock
from app.workspace.paths import (
    pending_reviewed_path,
    project_json_path,
    reviewed_dir,
    reviewed_path,
)


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
    corrections: Optional[dict[str, dict[str, Any]]] = None,
    prompt_id: Optional[str] = None,
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

    `corrections` is the per-field before/after diff of what the human changed
    in this save (shape `{field: {"before", "after"}}`). When non-empty it is
    persisted under `_corrections` AND increments the project-level
    `corrections_since_tune` counter (by the number of corrected fields) inside
    the same `project_lock` — that counter feeds the ambient "want me to
    /improve?" nudge. Absent / empty → no counter movement (backward compatible).
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

    # Anchor the ground truth to the prompt whose schema it was edited against.
    # `prompt_id` comes from the caller (the reviewer may have adopted a
    # prediction from an experiment on a non-active prompt); absent → the
    # project's active prompt, which is what a hand-typed review used. Minting
    # the stamp server-side keeps `run_id`/`ts` off the wire. Best-effort: a
    # missing/deleted prompt must never block a save of human work.
    run_stamp = None
    try:
        from app.eval.run_stamp import build_stamp
        from app.tools.prompt import read_active_prompt, read_prompt

        pv = (
            await read_prompt(workspace, project_id, prompt_id)
            if prompt_id
            else await read_active_prompt(workspace, project_id)
        )
        run_stamp = build_stamp("reviewed", None, pv)
    except Exception:  # noqa: BLE001
        run_stamp = None

    payload = Reviewed(
        entities=entities,
        source=source,
        notes=notes,
        notes_consumed=resolved_consumed,
        corrections=corrections or None,
        evidence=evidence,
        run=run_stamp,
    ).model_dump(by_alias=True, exclude_none=True, mode="json")
    async with project_lock(workspace, project_id):
        reviewed_dir(workspace, project_id).mkdir(parents=True, exist_ok=True)
        rp = reviewed_path(workspace, project_id, filename)
        # Snapshot this doc's PREVIOUS corrected-field set before we overwrite
        # the file, so the project counters can move by the delta (an edit then
        # reverted in a later save nets to zero instead of counting twice).
        old_fields: list[str] = []
        if rp.exists():
            try:
                prev = json.loads(rp.read_text())
                prev_corr = prev.get("_corrections")
                if isinstance(prev_corr, dict):
                    old_fields = list(prev_corr.keys())
            except (OSError, json.JSONDecodeError):
                pass
        atomic_write_json(rp, payload)
        # Pro-labeler draft becomes obsolete the moment human-verified ground
        # truth is written. Atomic delete inside the same project_lock so
        # nobody can observe a state where both files exist.
        pending = pending_reviewed_path(workspace, project_id, filename)
        if pending.exists():
            try:
                pending.unlink()
            except FileNotFoundError:
                pass
        # Reconcile the denormalized correction counters by the delta between
        # this doc's old and new corrected-field sets. Runs even when
        # `corrections` is empty — a revert ships no `_corrections` but must
        # still retire the doc's prior contribution. Done inside THIS lock (the
        # flock is non-reentrant, so we mutate the project.json dict directly).
        # Best-effort: a missing/garbled project.json never fails the save.
        new_fields = list(corrections.keys()) if corrections else []
        if old_fields or new_fields:
            from app.tools.projects import reconcile_corrections_in_blob

            pj = project_json_path(workspace, project_id)
            try:
                proj_blob = json.loads(pj.read_text())
                reconcile_corrections_in_blob(proj_blob, old_fields, new_fields)
                atomic_write_json(pj, proj_blob)
            except (OSError, json.JSONDecodeError):
                pass


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
