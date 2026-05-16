"""Delete-doc tool coverage. Pins the contract that every artifact keyed by
filename is wiped — file, sidecar, render cache, draft prediction, reviewed
JSON, and per-experiment predictions — so a re-upload starts clean."""
from pathlib import Path

import pytest

from app.tools.docs import delete_doc, list_docs, upload_doc
from app.tools.projects import create_project
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    doc_meta_path,
    doc_path,
    doc_render_dir,
    experiment_prediction_path,
    experiments_dir,
    prediction_draft_path,
    reviewed_path,
)


SAMPLE_PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>\nendobj\nxref\n0 1\n0000000000 65535 f\n%%EOF\n"


async def test_delete_doc_removes_file_and_sidecar(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    await upload_doc(workspace, pid, SAMPLE_PDF, "invoice.pdf")
    result = await delete_doc(workspace, pid, "invoice.pdf")
    assert result["removed"] is True
    assert "doc" in result["artifacts"]
    assert "meta" in result["artifacts"]
    assert not doc_path(workspace, pid, "invoice.pdf").exists()
    assert not doc_meta_path(workspace, pid, "invoice.pdf").exists()
    listed = await list_docs(workspace, pid)
    assert listed == []


async def test_delete_doc_wipes_render_cache(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    await upload_doc(workspace, pid, SAMPLE_PDF, "a.pdf")
    render_d = doc_render_dir(workspace, pid, "a.pdf")
    render_d.mkdir(parents=True)
    (render_d / "p1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    result = await delete_doc(workspace, pid, "a.pdf")
    assert "render_cache" in result["artifacts"]
    assert not render_d.exists()


async def test_delete_doc_wipes_predictions_and_reviewed(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    await upload_doc(workspace, pid, SAMPLE_PDF, "a.pdf")
    # seed a draft prediction + reviewed JSON
    atomic_write_json(prediction_draft_path(workspace, pid, "a.pdf"), {"entities": []})
    atomic_write_json(reviewed_path(workspace, pid, "a.pdf"), {"entities": []})
    # seed two experiment predictions (one for this doc, one unrelated to
    # confirm we only touch matching filenames)
    edir = experiments_dir(workspace, pid)
    (edir / "e_one" / "predictions").mkdir(parents=True)
    (edir / "e_two" / "predictions").mkdir(parents=True)
    atomic_write_json(
        experiment_prediction_path(workspace, pid, "e_one", "a.pdf"),
        {"entities": []},
    )
    atomic_write_json(
        experiment_prediction_path(workspace, pid, "e_two", "a.pdf"),
        {"entities": []},
    )
    atomic_write_json(
        experiment_prediction_path(workspace, pid, "e_one", "other.pdf"),
        {"entities": []},
    )

    result = await delete_doc(workspace, pid, "a.pdf")
    assert "prediction_draft" in result["artifacts"]
    assert "reviewed" in result["artifacts"]
    assert any(a.startswith("experiment_predictions") for a in result["artifacts"])

    assert not prediction_draft_path(workspace, pid, "a.pdf").exists()
    assert not reviewed_path(workspace, pid, "a.pdf").exists()
    assert not experiment_prediction_path(workspace, pid, "e_one", "a.pdf").exists()
    assert not experiment_prediction_path(workspace, pid, "e_two", "a.pdf").exists()
    # Unrelated doc's prediction stays untouched.
    assert experiment_prediction_path(workspace, pid, "e_one", "other.pdf").exists()


async def test_delete_doc_missing_returns_no_op(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    result = await delete_doc(workspace, pid, "ghost.pdf")
    assert result == {"removed": False, "filename": "ghost.pdf", "artifacts": []}


async def test_delete_doc_route_404_when_missing(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    monkeypatch.setenv("EMERGE_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("EMERGE_TEST_MODE", "1")
    from app.main import app

    pid = (await create_project(workspace, name="x"))["slug"]
    client = TestClient(app)
    r = client.delete(f"/lab/projects/{pid}/docs/by-name/ghost.pdf")
    assert r.status_code == 404
    assert r.json()["detail"] == "doc_not_found"


async def test_delete_doc_route_200_when_present(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    monkeypatch.setenv("EMERGE_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("EMERGE_TEST_MODE", "1")
    from app.main import app

    pid = (await create_project(workspace, name="x"))["slug"]
    await upload_doc(workspace, pid, SAMPLE_PDF, "real.pdf")
    client = TestClient(app)
    r = client.delete(f"/lab/projects/{pid}/docs/by-name/real.pdf")
    assert r.status_code == 200
    body = r.json()
    assert body["removed"] is True
    assert body["filename"] == "real.pdf"
    assert not doc_path(workspace, pid, "real.pdf").exists()
