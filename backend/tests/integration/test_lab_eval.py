import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.reviewed import ReviewedSource
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.docs import upload_doc
from app.tools.projects import create_project
from app.tools.reviewed import save_reviewed
from app.tools.schema import write_schema
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import metrics_dir, predictions_draft_dir, project_json_path


async def test_post_eval_returns_score(workspace: Path) -> None:
    pid = (await create_project(workspace, name="eval"))["slug"]
    await write_schema(
        workspace,
        pid,
        [SchemaField(name="invoice_no", type=FieldType.STRING, description="Invoice number")],
        reason="test",
        allow_structural=True,
    )
    meta = await upload_doc(workspace, pid, b"\x89PNG\r\n\x1a\nstub", "sample.png")
    filename = meta["filename"]
    atomic_write_json(
        predictions_draft_dir(workspace, pid) / f"{filename}.json",
        {"entities": [{"invoice_no": "INV-1"}]},
    )
    await save_reviewed(
        workspace,
        pid,
        filename,
        entities=[{"invoice_no": "INV-1"}],
        source=ReviewedSource.MANUAL,
    )

    client = TestClient(app)
    r = client.post(f"/lab/projects/{pid}/eval")

    assert r.status_code == 200
    body = r.json()
    assert body["macro_f1"] == 1.0
    assert body["n_reviewed"] == 1
    # M12: dir-form artifact replaces eval_*.json file.
    dirs = [
        p for p in metrics_dir(workspace, pid).iterdir()
        if p.is_dir() and p.name.startswith("eval_")
    ]
    assert len(dirs) == 1
    saved = json.loads((dirs[0] / "summary.json").read_text())
    assert saved["macro_f1"] == body["macro_f1"]


def test_post_eval_404_on_unknown_slug() -> None:
    """Post slug-transparency `p_INVALIDPATH` is a valid (if unusual) slug —
    no strict pid regex anymore. Existence check returns 404."""
    client = TestClient(app)
    r = client.post("/lab/projects/p_INVALIDPATH/eval")
    assert r.status_code == 404


def test_post_eval_404_on_missing_project() -> None:
    client = TestClient(app)
    r = client.post("/lab/projects/p_abcdefghijkl/eval")
    assert r.status_code == 404
    assert r.json()["detail"] == "project_not_found"


def test_post_eval_404_on_missing_schema(workspace: Path) -> None:
    pid = "p_abcdefghijkl"
    atomic_write_json(project_json_path(workspace, pid), {"name": "missing-schema"})

    client = TestClient(app)
    r = client.post(f"/lab/projects/{pid}/eval")

    assert r.status_code == 404
    assert r.json()["detail"] == "schema_not_found"


async def test_get_evals_latest_returns_score(workspace: Path) -> None:
    pid = (await create_project(workspace, name="latest"))["slug"]
    await write_schema(
        workspace,
        pid,
        [SchemaField(name="invoice_no", type=FieldType.STRING, description="Invoice number")],
        reason="test",
        allow_structural=True,
    )
    meta = await upload_doc(workspace, pid, b"\x89PNG\r\n\x1a\nstub", "sample.png")
    filename = meta["filename"]
    atomic_write_json(
        predictions_draft_dir(workspace, pid) / f"{filename}.json",
        {"entities": [{"invoice_no": "INV-1"}]},
    )
    await save_reviewed(
        workspace, pid, filename,
        entities=[{"invoice_no": "INV-1"}], source=ReviewedSource.MANUAL,
    )

    client = TestClient(app)
    # No eval yet → 404
    r0 = client.get(f"/lab/projects/{pid}/evals/latest")
    assert r0.status_code == 404
    assert r0.json()["detail"] == "eval_not_found"

    # Run /eval once
    assert client.post(f"/lab/projects/{pid}/eval").status_code == 200

    # Latest reflects the run
    r1 = client.get(f"/lab/projects/{pid}/evals/latest")
    assert r1.status_code == 200
    body = r1.json()
    assert body["macro_f1"] == 1.0
    assert body["n_reviewed"] == 1
    assert isinstance(body["per_field"], list) and body["per_field"][0]["field"] == "invoice_no"
    assert isinstance(body["ts"], str) and body["ts"].startswith("20")


async def test_get_evals_latest_picks_lex_last(workspace: Path) -> None:
    """Two eval files on disk → endpoint returns the lex-greatest filename
    (which equals the most-recent ts since filenames are
    `eval_YYYY-MM-DDTHH-MM-SSZ.json`)."""
    pid = (await create_project(workspace, name="lex"))["slug"]
    await write_schema(
        workspace, pid,
        [SchemaField(name="x", type=FieldType.STRING, description="x")],
        reason="test", allow_structural=True,
    )
    md = metrics_dir(workspace, pid)
    md.mkdir(parents=True, exist_ok=True)
    earlier = {"n_docs": 1, "n_reviewed": 1, "macro_f1": 0.50,
               "per_field": [{"field": "x", "tp": 1, "fp": 1, "fn": 1, "support": 2,
                              "precision": 0.50, "recall": 0.50, "f1": 0.50}],
               "errors": [], "ts": "2026-05-10T00-00-00Z", "schema_field_count": 1}
    later = {**earlier, "macro_f1": 0.97, "ts": "2026-05-11T00-00-00Z"}
    later["per_field"] = [{"field": "x", "tp": 1, "fp": 0, "fn": 0, "support": 1,
                           "precision": 1.0, "recall": 0.97, "f1": 0.97}]
    atomic_write_json(md / "eval_2026-05-10T00-00-00Z.json", earlier)
    atomic_write_json(md / "eval_2026-05-11T00-00-00Z.json", later)

    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}/evals/latest")
    assert r.status_code == 200
    assert r.json()["macro_f1"] == 0.97
    assert r.json()["ts"] == "2026-05-11T00-00-00Z"


def test_get_evals_latest_404_on_unknown_slug() -> None:
    """Slug shapes that previously failed the pid regex now pass safe_slug —
    404 from the existence check is the expected response."""
    client = TestClient(app)
    r = client.get("/lab/projects/p_INVALIDPATH/evals/latest")
    assert r.status_code == 404


def test_get_evals_latest_404_on_missing_project() -> None:
    client = TestClient(app)
    r = client.get("/lab/projects/p_abcdefghijkl/evals/latest")
    assert r.status_code == 404
    assert r.json()["detail"] == "project_not_found"
