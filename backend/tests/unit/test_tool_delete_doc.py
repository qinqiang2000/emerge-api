"""Delete-doc tool coverage. Pins two halves of the contract: every artifact
keyed by filename leaves the project — file, sidecar, draft prediction,
reviewed JSON, per-experiment predictions — so a re-upload starts clean; and
they leave by MOVING into one recoverable `_trash/` bundle rather than being
unlinked, because `reviewed/` is hand-corrected ground truth no re-run can
rebuild. The content-addressed caches stay put (shared across projects)."""
import json
from pathlib import Path

import pytest

from app.tools.docs import delete_doc, list_docs, rename_doc, upload_doc
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


async def test_delete_doc_preserves_content_cache(workspace: Path) -> None:
    # The render/textlayer/translate caches are content-addressed at the
    # workspace level (`.cache/_render/{sha}/`) and may be shared by the same
    # bytes in another project — so a per-project delete must NOT wipe them.
    pid = (await create_project(workspace, name="x"))["slug"]
    await upload_doc(workspace, pid, SAMPLE_PDF, "a.pdf")
    render_d = doc_render_dir(workspace, pid, "a.pdf")
    render_d.mkdir(parents=True)
    seeded = render_d / "p1.png"
    seeded.write_bytes(b"\x89PNG\r\n\x1a\n")
    result = await delete_doc(workspace, pid, "a.pdf")
    assert "render_cache" not in result["artifacts"]
    assert seeded.exists()


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
    assert "experiment/e_one" in result["artifacts"]
    assert "experiment/e_two" in result["artifacts"]

    assert not prediction_draft_path(workspace, pid, "a.pdf").exists()
    assert not reviewed_path(workspace, pid, "a.pdf").exists()
    assert not experiment_prediction_path(workspace, pid, "e_one", "a.pdf").exists()
    assert not experiment_prediction_path(workspace, pid, "e_two", "a.pdf").exists()
    # Unrelated doc's prediction stays untouched.
    assert experiment_prediction_path(workspace, pid, "e_one", "other.pdf").exists()


async def test_delete_doc_is_recoverable_from_trash(workspace: Path) -> None:
    # The whole point of the bundle: a mis-aimed delete must not destroy the
    # reviewed ground truth. Every member lands in ONE trash entry whose
    # manifest records where it came from, so a restore can replay it.
    from app.workspace.paths import trash_root

    pid = (await create_project(workspace, name="x"))["slug"]
    await upload_doc(workspace, pid, SAMPLE_PDF, "a.pdf")
    atomic_write_json(reviewed_path(workspace, pid, "a.pdf"), {"entities": [{"v": 1}]})

    result = await delete_doc(workspace, pid, "a.pdf")
    bundle = trash_root(workspace) / result["trashed_to"]
    assert bundle.is_dir()

    manifest = json.loads((bundle / "_manifest.json").read_text())
    by_role = {m["role"]: m for m in manifest["members"]}
    assert set(by_role) >= {"doc", "meta", "reviewed"}

    # Replaying the manifest puts every file back exactly where it was.
    for member in manifest["members"]:
        origin = workspace / member["origin"]
        origin.parent.mkdir(parents=True, exist_ok=True)
        (bundle / member["stored"]).rename(origin)
    assert doc_path(workspace, pid, "a.pdf").read_bytes() == SAMPLE_PDF
    restored = json.loads(reviewed_path(workspace, pid, "a.pdf").read_text())
    assert restored == {"entities": [{"v": 1}]}
    assert len(await list_docs(workspace, pid)) == 1


async def test_delete_doc_missing_returns_no_op(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    result = await delete_doc(workspace, pid, "ghost.pdf")
    assert result == {"removed": False, "filename": "ghost.pdf", "artifacts": []}


async def test_rename_doc_carries_every_artifact(workspace: Path) -> None:
    # A doc's filename is the primary key of its artifacts. Renaming must move
    # the whole set — a doc that arrives at its new name with no prediction and
    # no review history is the bug this guards.
    pid = (await create_project(workspace, name="x"))["slug"]
    await upload_doc(workspace, pid, SAMPLE_PDF, "a.pdf")
    atomic_write_json(prediction_draft_path(workspace, pid, "a.pdf"), {"entities": []})
    atomic_write_json(reviewed_path(workspace, pid, "a.pdf"), {"entities": [{"v": 1}]})
    (experiments_dir(workspace, pid) / "e_one" / "predictions").mkdir(parents=True)
    atomic_write_json(
        experiment_prediction_path(workspace, pid, "e_one", "a.pdf"), {"entities": []},
    )

    out = await rename_doc(workspace, pid, "a.pdf", "b.pdf")
    assert out == {
        "filename": "b.pdf",
        "previous": "a.pdf",
        "artifacts": ["doc", "meta", "prediction_draft", "reviewed", "experiment/e_one"],
    }

    for missing in (
        doc_path(workspace, pid, "a.pdf"),
        doc_meta_path(workspace, pid, "a.pdf"),
        prediction_draft_path(workspace, pid, "a.pdf"),
        reviewed_path(workspace, pid, "a.pdf"),
        experiment_prediction_path(workspace, pid, "e_one", "a.pdf"),
    ):
        assert not missing.exists(), f"{missing} left behind as an orphan"

    assert doc_path(workspace, pid, "b.pdf").read_bytes() == SAMPLE_PDF
    assert json.loads(reviewed_path(workspace, pid, "b.pdf").read_text()) == {
        "entities": [{"v": 1}]
    }
    assert experiment_prediction_path(workspace, pid, "e_one", "b.pdf").exists()
    # The sidecar's own `filename` field agrees with disk right away.
    assert json.loads(doc_meta_path(workspace, pid, "b.pdf").read_text())["filename"] == "b.pdf"
    listed = await list_docs(workspace, pid)
    assert [d["filename"] for d in listed] == ["b.pdf"]


async def test_rename_doc_inherits_extension_and_rejects_changing_it(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    await upload_doc(workspace, pid, SAMPLE_PDF, "a.pdf")

    # Bare name → keeps .pdf (the extension selects the extract path).
    out = await rename_doc(workspace, pid, "a.pdf", "2026 发票")
    assert out["filename"] == "2026 发票.pdf"

    with pytest.raises(ValueError, match="extension"):
        await rename_doc(workspace, pid, "2026 发票.pdf", "c.txt")


async def test_rename_doc_rejects_collision_and_missing(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    await upload_doc(workspace, pid, SAMPLE_PDF, "a.pdf")
    await upload_doc(workspace, pid, SAMPLE_PDF, "b.pdf")

    with pytest.raises(ValueError, match="already exists"):
        await rename_doc(workspace, pid, "a.pdf", "b.pdf")
    with pytest.raises(FileNotFoundError):
        await rename_doc(workspace, pid, "ghost.pdf", "z.pdf")
    # Failed rename leaves both docs where they were.
    assert doc_path(workspace, pid, "a.pdf").exists()
    assert doc_path(workspace, pid, "b.pdf").exists()


async def test_rename_doc_route(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    monkeypatch.setenv("EMERGE_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("EMERGE_TEST_MODE", "1")
    from app.main import app

    pid = (await create_project(workspace, name="x"))["slug"]
    await upload_doc(workspace, pid, SAMPLE_PDF, "real.pdf")
    client = TestClient(app)

    r = client.post(
        f"/lab/projects/{pid}/docs/by-name/real.pdf/rename",
        json={"new_filename": "renamed.pdf"},
    )
    assert r.status_code == 200
    assert r.json()["filename"] == "renamed.pdf"
    assert doc_path(workspace, pid, "renamed.pdf").exists()

    # Collision → 400, not a silent overwrite.
    await upload_doc(workspace, pid, SAMPLE_PDF, "other.pdf")
    r = client.post(
        f"/lab/projects/{pid}/docs/by-name/other.pdf/rename",
        json={"new_filename": "renamed.pdf"},
    )
    assert r.status_code == 400
    r = client.post(
        f"/lab/projects/{pid}/docs/by-name/ghost.pdf/rename",
        json={"new_filename": "z.pdf"},
    )
    assert r.status_code == 404


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
