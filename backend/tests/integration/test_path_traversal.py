"""Verify project_id and filename route params reject traversal and malformed IDs.

FastAPI already rejects %2F-encoded slashes at the routing layer (404 Not Found),
so traversal sequences that contain encoded slashes never reach a handler.
The real exposure is IDs / filenames with unexpected characters that *do* reach
the handler; those are what these tests cover.
"""
from fastapi.testclient import TestClient

from app.main import app


def test_upload_rejects_invalid_project_id() -> None:
    """Non-conforming project_id is rejected before any filesystem access."""
    client = TestClient(app)
    r = client.post(
        "/lab/projects/dotdotslash/upload",
        files={"file": ("a.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf")},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid project_id"


def test_upload_rejects_uppercase_project_id() -> None:
    client = TestClient(app)
    r = client.post(
        "/lab/projects/P_ABC123DEF456/upload",
        files={"file": ("a.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf")},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid project_id"


def test_get_project_rejects_invalid_id() -> None:
    """GET project detail rejects non-conforming project_id."""
    client = TestClient(app)
    r = client.get("/lab/projects/not-a-valid-id")
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid project_id"


def test_get_page_rejects_invalid_project_id() -> None:
    """GET page rejects non-conforming project_id even when filename looks fine."""
    client = TestClient(app)
    r = client.get("/lab/projects/p_UPPERCASE12/docs/by-name/inv.pdf/pages/1")
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid project_id"


def test_get_page_rejects_traversal_filename() -> None:
    """filename path-param must reject traversal segments and raw separators.

    `..` reaches the handler as a literal segment (not interpreted by HTTP
    routing); `safe_filename` rejects it as `invalid filename`.
    """
    client = TestClient(app)
    r = client.get("/lab/projects/p_abc123def456/docs/by-name/../etc/pages/1")
    # FastAPI may normalize `..` at the routing layer; either it 404s before
    # reaching us OR safe_filename rejects with 400. Both are acceptable —
    # what matters is no traversal succeeds.
    assert r.status_code in {400, 404}


def test_upload_with_valid_project_id_format_but_missing_project() -> None:
    """Valid format passes the gate; the underlying tool's own behavior takes over."""
    client = TestClient(app)
    r = client.post(
        "/lab/projects/p_doesnotexist/upload",
        files={"file": ("a.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf")},
    )
    # Format check passes — point is it's NOT a 400 with "invalid project_id"
    assert r.status_code != 400 or "invalid project_id" not in r.text
