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
from app.workspace.paths import predictions_draft_dir


async def test_post_eval_returns_score(workspace: Path) -> None:
    pid = await create_project(workspace, name="eval")
    await write_schema(
        workspace,
        pid,
        [SchemaField(name="invoice_no", type=FieldType.STRING, description="Invoice number")],
        reason="test",
        allow_structural=True,
    )
    doc_id = await upload_doc(workspace, pid, b"png", "sample.png")
    atomic_write_json(
        predictions_draft_dir(workspace, pid) / f"{doc_id}.json",
        {"entities": [{"invoice_no": "INV-1"}]},
    )
    await save_reviewed(
        workspace,
        pid,
        doc_id,
        entities=[{"invoice_no": "INV-1"}],
        source=ReviewedSource.MANUAL,
    )

    client = TestClient(app)
    r = client.post(f"/lab/projects/{pid}/eval")

    assert r.status_code == 200
    body = r.json()
    assert body["macro_f1"] == 1.0
    assert body["n_reviewed"] == 1


def test_post_eval_400_on_bad_pid() -> None:
    client = TestClient(app)
    r = client.post("/lab/projects/p_INVALIDPATH/eval")
    assert r.status_code == 400
