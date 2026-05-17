"""`get_surface_state(surface='review', slug, filename)` aggregates per-doc
disk state for the agent — review_status, prediction/reviewed presence,
notes, evidence pages, experiment coverage. Mirrors what the frontend's
`useDocs` store derives from the docs listing so the agent's answer to "what
status is this doc in" matches what the user sees in the badge."""
from __future__ import annotations

from pathlib import Path

from app.schemas.reviewed import ReviewedSource
from app.tools.projects import create_project
from app.tools.reviewed import save_reviewed
from app.tools.surface_state import get_surface_state
from app.workspace.atomic import atomic_write_bytes, atomic_write_json
from app.workspace.paths import (
    doc_meta_path,
    doc_path,
    docs_dir,
    docs_meta_dir,
    experiment_meta_path,
    experiment_prediction_path,
    experiment_predictions_dir,
    predictions_draft_dir,
)


async def _seed_doc(workspace: Path, slug: str, filename: str = "x.pdf") -> None:
    """Drop a tiny doc + sidecar so get_surface_state's existence check passes."""
    docs_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    docs_meta_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(doc_path(workspace, slug, filename), b"%PDF-stub")
    atomic_write_json(doc_meta_path(workspace, slug, filename), {
        "filename": filename,
        "original_name": filename,
        "ext": "pdf",
        "sha256": "deadbeef",
        "page_count": 3,
        "uploaded_at": "2026-01-01T00:00:00+00:00",
    })


async def test_surface_state_unsupported_surface(workspace: Path) -> None:
    out = await get_surface_state(workspace, surface="home", slug="x")
    assert out["ok"] is False
    assert out["error"]["error_code"] == "surface_unsupported"


async def test_surface_state_review_missing_filename(workspace: Path) -> None:
    out = await get_surface_state(workspace, surface="review", slug="x")
    assert out["ok"] is False
    assert out["error"]["error_code"] == "surface_missing_param"


async def test_surface_state_review_doc_not_found(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    out = await get_surface_state(
        workspace, surface="review", slug=pid, filename="nope.pdf",
    )
    assert out["ok"] is False
    assert out["error"]["error_code"] == "doc_not_found"


async def test_surface_state_review_unprocessed(workspace: Path) -> None:
    """Doc exists, no prediction, no reviewed → 'unprocessed'."""
    pid = (await create_project(workspace, name="x"))["slug"]
    await _seed_doc(workspace, pid, "x.pdf")
    out = await get_surface_state(
        workspace, surface="review", slug=pid, filename="x.pdf",
    )
    assert out["ok"] is True
    assert out["review_status"] == "unprocessed"
    assert out["has_prediction"] is False
    assert out["has_reviewed"] is False
    assert out["has_pending"] is False
    assert out["page_count"] == 3
    assert out["entity_count"] == 0
    assert out["experiments_with_prediction"] == []


async def test_surface_state_review_has_pending_flag(workspace: Path) -> None:
    """has_pending flips True when reviewed/_pending/{filename}.json exists.
    review_status enum stays at {unprocessed, pending, reviewed} — pre-labeled
    docs surface their distinction via the banner, not via a new enum value."""
    from app.workspace.paths import pending_reviewed_dir, pending_reviewed_path
    pid = (await create_project(workspace, name="x"))["slug"]
    await _seed_doc(workspace, pid, "x.pdf")
    pending_reviewed_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        pending_reviewed_path(workspace, pid, "x.pdf"),
        {
            "entities": [{}],
            "labeler_model": "gemini-pro-latest",
            "created_at": "2026-05-17T00:00:00+00:00",
        },
    )
    out = await get_surface_state(
        workspace, surface="review", slug=pid, filename="x.pdf",
    )
    assert out["has_pending"] is True
    # No flash prediction either way — pre-labeled doc with no _draft means
    # review_status stays 'unprocessed' (enum unchanged).
    assert out["review_status"] == "unprocessed"
    assert out["has_prediction"] is False
    assert out["has_reviewed"] is False


async def test_surface_state_review_pending(workspace: Path) -> None:
    """Prediction exists, no reviewed → 'pending'."""
    pid = (await create_project(workspace, name="x"))["slug"]
    await _seed_doc(workspace, pid, "x.pdf")
    predictions_draft_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        predictions_draft_dir(workspace, pid) / "x.pdf.json",
        {"entities": [{"buyer_name": "ACME"}], "_evidence": [{"buyer_name": 2}]},
    )
    out = await get_surface_state(
        workspace, surface="review", slug=pid, filename="x.pdf",
    )
    assert out["review_status"] == "pending"
    assert out["has_prediction"] is True
    assert out["has_reviewed"] is False
    assert out["entity_count"] == 1
    assert out["evidence"] == [{"buyer_name": 2}]


async def test_surface_state_review_reviewed(workspace: Path) -> None:
    """Reviewed exists → 'reviewed'; notes + evidence come from reviewed file."""
    pid = (await create_project(workspace, name="x"))["slug"]
    await _seed_doc(workspace, pid, "x.pdf")
    await save_reviewed(
        workspace, pid, "x.pdf",
        entities=[{"buyer_name": "ACME"}],
        source=ReviewedSource.MANUAL,
        notes={"buyer_name": "double-checked"},
        evidence=[{"buyer_name": 1}],
    )
    out = await get_surface_state(
        workspace, surface="review", slug=pid, filename="x.pdf",
    )
    assert out["review_status"] == "reviewed"
    assert out["has_reviewed"] is True
    assert out["notes"] == {"buyer_name": "double-checked"}
    assert out["evidence"] == [{"buyer_name": 1}]


async def test_surface_state_review_lists_experiments(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    await _seed_doc(workspace, pid, "x.pdf")
    # Manually fabricate an experiment dir + prediction file. We bypass
    # create_experiment to avoid pulling the full prompt/model fixture.
    eid = "exp_test1"
    experiment_predictions_dir(workspace, pid, eid).mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        experiment_meta_path(workspace, pid, eid),
        {
            "experiment_id": eid,
            "label": "test",
            "prompt_id": "pr_baseline",
            "model_id": "m_default",
            "status": "draft",
            "created_at": "2026-01-01T00:00:00+00:00",
            "promoted_at": None,
            "notes": "",
            "eval": None,
        },
    )
    atomic_write_json(
        experiment_prediction_path(workspace, pid, eid, "x.pdf"),
        {"entities": [{"buyer_name": "X"}]},
    )
    out = await get_surface_state(
        workspace, surface="review", slug=pid, filename="x.pdf",
    )
    assert out["experiments_with_prediction"] == [eid]
