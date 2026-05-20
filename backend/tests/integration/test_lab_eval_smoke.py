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
from app.workspace.paths import metrics_dir, predictions_draft_dir


async def test_eval_full_pipeline(workspace: Path):
    pid = (await create_project(workspace, name="smoke"))["slug"]
    await write_schema(
        workspace,
        pid,
        [
            SchemaField(name="invoice_no", type=FieldType.STRING, description="Invoice number"),
            SchemaField(name="total", type=FieldType.NUMBER, description="Invoice total"),
        ],
        reason="smoke",
        allow_structural=True,
    )

    d1_meta = await upload_doc(workspace, pid, b"%PDF-1.4\n%%EOF\n", "d1.pdf")
    d2_meta = await upload_doc(workspace, pid, b"%PDF-1.4\n%%EOF\n", "d2.pdf")
    d1 = d1_meta["filename"]
    d2 = d2_meta["filename"]

    pdir = predictions_draft_dir(workspace, pid)
    atomic_write_json(
        pdir / f"{d1}.json",
        {"entities": [{"invoice_no": "INV-1", "total": 100}]},
    )
    atomic_write_json(
        pdir / f"{d2}.json",
        {"entities": [{"invoice_no": "WRONG", "total": 200}]},
    )

    await save_reviewed(
        workspace,
        pid,
        d1,
        entities=[{"invoice_no": "INV-1", "total": 100}],
        source=ReviewedSource.MANUAL,
    )
    await save_reviewed(
        workspace,
        pid,
        d2,
        entities=[{"invoice_no": "INV-2", "total": 200}],
        source=ReviewedSource.MANUAL,
    )

    client = TestClient(app)
    response = client.post(f"/lab/projects/{pid}/eval")

    assert response.status_code == 200
    body = response.json()
    assert body["n_reviewed"] == 2

    # M12.x: per-field carries `accuracy/correct/total`; F1 family is None.
    per_field = {field["field"]: field for field in body["per_field"]}
    # invoice_no: 1 correct + 1 wrong = 0.5 accuracy
    assert per_field["invoice_no"]["correct"] == 1
    assert per_field["invoice_no"]["total"] == 2
    assert per_field["invoice_no"]["accuracy"] == 0.5
    assert per_field["invoice_no"]["f1"] is None
    # total: 2 correct out of 2
    assert per_field["total"]["correct"] == 2
    assert per_field["total"]["total"] == 2
    assert per_field["total"]["accuracy"] == 1.0

    # M12: dir-form artifact replaces eval_*.json file.
    dirs = [
        p for p in metrics_dir(workspace, pid).iterdir()
        if p.is_dir() and p.name.startswith("eval_")
    ]
    assert len(dirs) == 1
    saved = json.loads((dirs[0] / "summary.json").read_text())
    assert saved["field_accuracy_macro"] == body["field_accuracy_macro"]
