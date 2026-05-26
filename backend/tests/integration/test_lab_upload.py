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
    assert body["kind"] == "doc"


def test_staging_upload_accepts_yaml_with_schema_kind() -> None:
    """Phase B: staging widens beyond pdf/png/jpg. yaml → kind=schema so the
    frontend chip can route through the agent's "import?" prompt."""
    client = TestClient(app)
    payload = b"- name: invoice_number\n  type: string\n  description: id\n"
    files = {"file": ("fields.yaml", io.BytesIO(payload), "text/yaml")}
    r = client.post("/lab/uploads/staging", files=files)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "schema"
    assert body["ext"] == "yaml"


def test_staging_upload_accepts_csv_with_data_kind() -> None:
    client = TestClient(app)
    payload = b"a,b\n1,2\n"
    r = client.post(
        "/lab/uploads/staging",
        files={"file": ("rows.csv", io.BytesIO(payload), "text/csv")},
    )
    assert r.status_code == 200
    assert r.json()["kind"] == "data"


def test_staging_upload_rejects_oversize_text() -> None:
    """Text-shaped extensions cap at 256 KiB; bigger means user grabbed the
    wrong file, not a config."""
    client = TestClient(app)
    huge = b"a" * (256 * 1024 + 1)
    r = client.post(
        "/lab/uploads/staging",
        files={"file": ("huge.txt", io.BytesIO(huge), "text/plain")},
    )
    assert r.status_code == 400


def test_staging_upload_rejects_unknown_extension() -> None:
    """Anything outside the doc + text allowlists 400s before disk."""
    client = TestClient(app)
    r = client.post(
        "/lab/uploads/staging",
        files={"file": ("evil.exe", io.BytesIO(b"MZ"), "application/octet-stream")},
    )
    assert r.status_code == 400


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
    assert r.json() == {"filename": "scan.pdf", "kind": "doc"}
    assert (
        workspace / pid / "chats" / chat_id / "attachments" / "scan.pdf"
    ).read_bytes() == pdf
    # docs/ untouched.
    assert not (workspace / pid / "docs" / "scan.pdf").exists()


async def test_attach_to_chat_accepts_yaml_with_schema_kind(workspace: Path) -> None:
    """Phase B: in-project attach now accepts yaml/json/csv/txt/md too, with
    the same `kind` envelope as staging."""
    pid = (await create_project(workspace, name="x"))["slug"]
    chat_id = "c_abc123def456"
    client = TestClient(app)
    payload = b"- name: invoice_number\n  type: string\n  description: id\n"
    r = client.post(
        f"/lab/projects/{pid}/chats/{chat_id}/attach",
        files={"file": ("fields.yaml", io.BytesIO(payload), "text/yaml")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"filename": "fields.yaml", "kind": "schema"}
    landed = workspace / pid / "chats" / chat_id / "attachments" / "fields.yaml"
    assert landed.read_bytes() == payload


async def test_attach_to_chat_accepts_csv_with_data_kind(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    chat_id = "c_abc123def456"
    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{pid}/chats/{chat_id}/attach",
        files={"file": ("rows.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")},
    )
    assert r.status_code == 200
    assert r.json()["kind"] == "data"


async def test_attach_to_chat_rejects_oversize_text(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    chat_id = "c_abc123def456"
    client = TestClient(app)
    huge = b"a" * (256 * 1024 + 1)
    r = client.post(
        f"/lab/projects/{pid}/chats/{chat_id}/attach",
        files={"file": ("huge.txt", io.BytesIO(huge), "text/plain")},
    )
    assert r.status_code == 400


async def test_attach_to_chat_rejects_unknown_extension(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    chat_id = "c_abc123def456"
    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{pid}/chats/{chat_id}/attach",
        files={"file": ("evil.exe", io.BytesIO(b"MZ"), "application/octet-stream")},
    )
    assert r.status_code == 400


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


async def test_ingest_local_endpoint_imports_directory(
    workspace: Path, tmp_path: Path, monkeypatch,
) -> None:
    """POST /lab/projects/{slug}/ingest-local walks a server-local path,
    silently skips non-pdf/png/jpg, and lands the rest in `docs/`."""
    src = tmp_path / "scans"
    src.mkdir()
    (src / "a.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    (src / "b.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    (src / "junk.txt").write_bytes(b"hello")
    # Whitelist the test's tmp_path via env override so the default allowlist
    # doesn't have to include pytest's tmpdir.
    monkeypatch.setenv("EMERGE_INGEST_LOCAL_EXTRA_ROOTS", str(tmp_path))
    pid = (await create_project(workspace, name="x"))["slug"]
    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{pid}/ingest-local",
        json={"path": str(src), "target": "docs"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert {f["filename"] for f in body["ingested"]} == {"a.pdf", "b.png"}
    assert body["skipped"] == [{"name": "junk.txt", "reason": "not pdf/png/jpg"}]
    assert (workspace / pid / "docs" / "a.pdf").exists()


async def test_ingest_local_endpoint_rejects_outside_allowlist(
    workspace: Path, tmp_path: Path,
) -> None:
    """No env override → tmp_path is NOT under the built-in defaults
    (/tmp, ~/Downloads, ..., repo root), so the route must 400."""
    src = tmp_path / "scans"
    src.mkdir()
    (src / "a.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    pid = (await create_project(workspace, name="x"))["slug"]
    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{pid}/ingest-local",
        json={"path": str(src)},
    )
    assert r.status_code == 400
    assert "allowlist" in r.json()["detail"]


async def test_ingest_local_endpoint_requires_path(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    client = TestClient(app)
    r = client.post(f"/lab/projects/{pid}/ingest-local", json={})
    assert r.status_code == 400
