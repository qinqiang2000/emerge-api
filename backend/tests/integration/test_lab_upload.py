import io
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.tools.projects import create_project


async def test_upload_pdf(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    client = TestClient(app)
    files = {"file": ("a.pdf", io.BytesIO(b"%PDF-1.4\n%%EOF\n"), "application/pdf")}
    r = client.post(f"/lab/projects/{pid}/upload", files=files)
    assert r.status_code == 200
    body = r.json()
    assert body["doc_id"].startswith("d_")
    assert (workspace / pid / "docs" / f"{body['doc_id']}.pdf").exists()


def test_upload_rejects_unsupported_extension() -> None:
    client = TestClient(app)
    files = {"file": ("a.docx", io.BytesIO(b"x"), "application/vnd.docx")}
    r = client.post("/lab/projects/p_zzz/upload", files=files)
    assert r.status_code == 400
