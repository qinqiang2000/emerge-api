import io
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.tools.projects import create_project


async def test_upload_pdf(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    client = TestClient(app)
    files = {"file": ("invoice.pdf", io.BytesIO(b"%PDF-1.4\n%%EOF\n"), "application/pdf")}
    r = client.post(f"/lab/projects/{pid}/upload", files=files)
    assert r.status_code == 200
    body = r.json()
    # Filename is the only handle now — no `doc_id`.
    assert body["filename"] == "invoice.pdf"
    assert body["ext"] == "pdf"
    assert "doc_id" not in body
    assert (workspace / pid / "docs" / "invoice.pdf").exists()


async def test_upload_dedup_collision(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    client = TestClient(app)
    pdf = b"%PDF-1.4\n%%EOF\n"
    r1 = client.post(
        f"/lab/projects/{pid}/upload",
        files={"file": ("a.pdf", io.BytesIO(pdf), "application/pdf")},
    )
    r2 = client.post(
        f"/lab/projects/{pid}/upload",
        files={"file": ("a.pdf", io.BytesIO(pdf), "application/pdf")},
    )
    assert r1.json()["filename"] == "a.pdf"
    assert r2.json()["filename"] == "a (1).pdf"


def test_upload_rejects_unsupported_extension() -> None:
    client = TestClient(app)
    files = {"file": ("a.docx", io.BytesIO(b"x"), "application/vnd.docx")}
    r = client.post("/lab/projects/p_zzz/upload", files=files)
    assert r.status_code == 400


def test_staging_upload_returns_token() -> None:
    """Pre-project staging route: accepts a file without a pid and returns a
    stage_token the frontend pins to a chip until the chat turn fires."""
    client = TestClient(app)
    files = {"file": ("a.pdf", io.BytesIO(b"%PDF-1.4\n%%EOF\n"), "application/pdf")}
    r = client.post("/lab/uploads/staging", files=files)
    assert r.status_code == 200
    body = r.json()
    assert body["stage_token"].startswith("st_")
    assert body["filename"] == "a.pdf"
    assert body["ext"] == "pdf"


def test_staging_upload_rejects_spoofed_extension() -> None:
    """Magic-byte sniff at the staging door — same defence as upload_doc."""
    client = TestClient(app)
    files = {"file": ("scan.png", io.BytesIO(b"<!doctype html>"), "image/png")}
    r = client.post("/lab/uploads/staging", files=files)
    assert r.status_code == 400
