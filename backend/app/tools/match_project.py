"""Match-project lifecycle: create + read.

A match project reuses the whole project spine (`create_project`) but stamps
`project_type="match"` and carries anchor/source references in its
`project.json`. It does NOT re-extract — it references already-existing extract
projects whose `predictions/_draft/` the engine reads. Per the design's three
implementation corrections: we reuse `project_type`, not a new `kind` field.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.tools.projects import create_project, update_project
from app.workspace.paths import (
    match_prompts_dir,
    matches_dir,
    project_json_path,
    reviewed_matches_dir,
)


class MatchProjectError(Exception):
    """Raised for invalid match-project construction (bad/missing anchor or
    source references). Carries a stable `error_code` for the envelope."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.error_message_en = message


def _read_project(workspace: Path, slug: str) -> dict[str, Any] | None:
    pj = project_json_path(workspace, slug)
    if not pj.exists():
        return None
    try:
        return json.loads(pj.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _validate_extract_ref(workspace: Path, slug: str, role: str) -> None:
    """A referenced anchor/source must be an existing, NON-match project.
    Raises MatchProjectError otherwise."""
    blob = _read_project(workspace, slug)
    if blob is None:
        raise MatchProjectError(
            "match_ref_not_found",
            f"{role} project '{slug}' does not exist",
        )
    if blob.get("project_type") == "match":
        raise MatchProjectError(
            "match_ref_is_match_project",
            f"{role} project '{slug}' is itself a match project; "
            "anchor/source must reference extract projects",
        )


async def create_match_project(
    workspace: Path,
    *,
    name: str,
    anchor: str,
    sources: list[str],
) -> dict[str, str]:
    """Create a match project referencing `anchor` + `sources` (existing extract
    projects). Validates every reference, then writes the references onto the
    fresh project's `project.json` and lays down the match-prompt / matches /
    reviewed_matches subdirs. Returns `{project_id, slug}`.
    """
    if not sources:
        raise MatchProjectError(
            "match_no_sources",
            "a match project needs at least one source project",
        )
    # Validate references BEFORE minting the skeleton so a bad ref doesn't leave
    # an orphan project dir behind.
    _validate_extract_ref(workspace, anchor, "anchor")
    seen: set[str] = set()
    for s in sources:
        if s == anchor:
            raise MatchProjectError(
                "match_source_is_anchor",
                f"source '{s}' is the same as the anchor",
            )
        if s in seen:
            raise MatchProjectError(
                "match_duplicate_source",
                f"source '{s}' is listed more than once",
            )
        seen.add(s)
        _validate_extract_ref(workspace, s, "source")

    out = await create_project(workspace, name=name, project_type="match")
    slug = out["slug"]
    await update_project(
        workspace,
        slug,
        {
            "anchor_project": anchor,
            "source_projects": list(sources),
            "active_match_prompt_id": None,
        },
    )
    match_prompts_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    matches_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    reviewed_matches_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    return out


def is_match_project(workspace: Path, slug: str) -> bool:
    blob = _read_project(workspace, slug)
    return bool(blob and blob.get("project_type") == "match")


async def read_match_project(workspace: Path, slug: str) -> dict[str, Any]:
    """Return `{slug, name, anchor_project, source_projects,
    active_match_prompt_id}` for a match project. Raises MatchProjectError if
    the slug isn't a match project."""
    blob = _read_project(workspace, slug)
    if blob is None:
        raise MatchProjectError(
            "match_project_not_found", f"project '{slug}' does not exist"
        )
    if blob.get("project_type") != "match":
        raise MatchProjectError(
            "not_a_match_project", f"project '{slug}' is not a match project"
        )
    return {
        "slug": slug,
        "name": blob.get("name"),
        "anchor_project": blob.get("anchor_project"),
        "source_projects": list(blob.get("source_projects") or []),
        "active_match_prompt_id": blob.get("active_match_prompt_id"),
    }
