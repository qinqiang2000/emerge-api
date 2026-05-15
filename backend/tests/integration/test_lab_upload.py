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


async def test_attach_to_chat_endpoint_writes_file_and_returns_filename(
    workspace: Path,
) -> None:
    """In-project paste path: POST /lab/projects/{slug}/chats/{cid}/attach
    writes to `chats/<cid>/attachments/<name>`, NOT to `docs/`."""
    pid = (await create_project(workspace, name="x"))["slug"]
    chat_id = "c_abc123def456"
    client = TestClient(app)
    pdf = b"%PDF-1.4\n%%EOF\n"
    r = client.post(
        f"/lab/projects/{pid}/chats/{chat_id}/attach",
        files={"file": ("scan.pdf", io.BytesIO(pdf), "application/pdf")},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"filename": "scan.pdf"}
    assert (
        workspace / pid / "chats" / chat_id / "attachments" / "scan.pdf"
    ).read_bytes() == pdf
    # docs/ untouched.
    assert not (workspace / pid / "docs" / "scan.pdf").exists()


async def test_attach_to_chat_dedupes_collisions(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    chat_id = "c_abc123def456"
    client = TestClient(app)
    pdf = b"%PDF-1.4\n%%EOF\n"
    r1 = client.post(
        f"/lab/projects/{pid}/chats/{chat_id}/attach",
        files={"file": ("dup.pdf", io.BytesIO(pdf), "application/pdf")},
    )
    r2 = client.post(
        f"/lab/projects/{pid}/chats/{chat_id}/attach",
        files={"file": ("dup.pdf", io.BytesIO(pdf), "application/pdf")},
    )
    assert r1.json()["filename"] == "dup.pdf"
    assert r2.json()["filename"] == "dup (1).pdf"


async def test_attach_to_chat_rejects_spoofed_bytes(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    chat_id = "c_abc123def456"
    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{pid}/chats/{chat_id}/attach",
        files={"file": ("evil.png", io.BytesIO(b"<!doctype html>"), "image/png")},
    )
    assert r.status_code == 400


async def test_get_chat_attachment_serves_bytes(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    chat_id = "c_abc123def456"
    client = TestClient(app)
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    client.post(
        f"/lab/projects/{pid}/chats/{chat_id}/attach",
        files={"file": ("a.png", io.BytesIO(png), "image/png")},
    )
    r = client.get(f"/lab/projects/{pid}/chats/{chat_id}/attachments/a.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content == png


async def test_get_chat_attachment_404_when_missing(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    chat_id = "c_abc123def456"
    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}/chats/{chat_id}/attachments/ghost.png")
    assert r.status_code == 404
