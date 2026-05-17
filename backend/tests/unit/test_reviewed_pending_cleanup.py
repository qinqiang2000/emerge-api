"""save_reviewed must atomically delete the matching `_pending/` draft.

The Pro Labeler writes a draft to `reviewed/_pending/{filename}.json`; the
moment the boss verifies and saves, that draft is obsolete — `reviewed/`
becomes the only ground truth. The cleanup is inside the same `project_lock`
as the reviewed-file write so no observer sees both states.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.schemas.reviewed import ReviewedSource
from app.tools.projects import create_project
from app.tools.reviewed import save_reviewed
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    pending_reviewed_dir,
    pending_reviewed_path,
    reviewed_path,
)


def _seed_pending(workspace: Path, slug: str, filename: str) -> None:
    pending_reviewed_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        pending_reviewed_path(workspace, slug, filename),
        {
            "entities": [{"invoice_no": "DRAFT"}],
            "labeler_model": "gemini-pro-latest",
            "created_at": "2026-05-17T00:00:00+00:00",
        },
    )


async def test_save_reviewed_deletes_matching_pending(workspace: Path) -> None:
    slug = (await create_project(workspace, name="x"))["slug"]
    _seed_pending(workspace, slug, "inv-1.pdf")
    assert pending_reviewed_path(workspace, slug, "inv-1.pdf").exists()

    await save_reviewed(
        workspace, slug, "inv-1.pdf",
        entities=[{"invoice_no": "INV-1"}],
        source=ReviewedSource.MANUAL,
    )
    assert reviewed_path(workspace, slug, "inv-1.pdf").exists()
    assert not pending_reviewed_path(workspace, slug, "inv-1.pdf").exists(), (
        "pending draft must be removed once the boss saves ground truth"
    )


async def test_save_reviewed_without_pending_is_noop(workspace: Path) -> None:
    """No pending file present — save_reviewed must not raise."""
    slug = (await create_project(workspace, name="x"))["slug"]
    await save_reviewed(
        workspace, slug, "fresh.pdf",
        entities=[{"x": 1}], source=ReviewedSource.MANUAL,
    )
    assert reviewed_path(workspace, slug, "fresh.pdf").exists()


async def test_save_reviewed_only_deletes_matching_filename(workspace: Path) -> None:
    """Pending for a different filename must NOT be deleted."""
    slug = (await create_project(workspace, name="x"))["slug"]
    _seed_pending(workspace, slug, "a.pdf")
    _seed_pending(workspace, slug, "b.pdf")

    await save_reviewed(
        workspace, slug, "a.pdf",
        entities=[{}], source=ReviewedSource.MANUAL,
    )
    assert not pending_reviewed_path(workspace, slug, "a.pdf").exists()
    # b.pdf draft is untouched.
    blob_b = json.loads(pending_reviewed_path(workspace, slug, "b.pdf").read_text())
    assert blob_b["labeler_model"] == "gemini-pro-latest"
