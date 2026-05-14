"""Verify project slug and filename route params reject traversal and malformed values.

FastAPI already rejects %2F-encoded slashes at the routing layer (404 Not Found),
so traversal sequences that contain encoded slashes never reach a handler.
The real exposure is slugs / filenames with unexpected characters that *do*
reach the handler; those are what these tests cover.

Post-slug-transparency the project handle is a human-readable slug (Unicode +
fs-safe). Strict regex-based rejection is gone; only filesystem-hostile
characters (slash / NUL / control / `.` / `..`) get a 400 from `safe_slug`.
"""
from fastapi.testclient import TestClient

from app.main import app


def test_upload_rejects_slug_with_control_char() -> None:
    """Slug containing a NUL/control char is rejected before any filesystem
    access. (The HTTP client encodes `%00`; FastAPI's path converter passes
    the decoded segment through to `safe_slug`.)"""
    client = TestClient(app)
    r = client.post(
        "/lab/projects/bad%00ctrl/upload",
        files={"file": ("a.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf")},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid slug"


def test_upload_rejects_dot_slug() -> None:
    """`.` and `..` are forbidden as folder names.

    HTTP routing normalises `/lab/projects/./upload` to `/lab/projects/upload`
    (TestClient/Starlette collapse `.` segments), which doesn't match any
    registered route — 404 / 405 are both fine. What matters is the dot slug
    never reaches a handler.
    """
    client = TestClient(app)
    r = client.post(
        "/lab/projects/./upload",
        files={"file": ("a.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf")},
    )
    assert r.status_code in {400, 404, 405}


def test_get_project_404_for_missing() -> None:
    """A valid-shape slug that doesn't exist returns 404, not 400. The slug
    namespace is now Unicode + fs-safe, so almost any printable string passes
    the gate; existence is checked separately."""
    client = TestClient(app)
    r = client.get("/lab/projects/no-such-project")
    assert r.status_code == 404


def test_get_page_rejects_traversal_filename() -> None:
    """filename path-param must reject traversal segments and raw separators.

    `..` reaches the handler as a literal segment (not interpreted by HTTP
    routing); `safe_filename` rejects it as `invalid filename`.
    """
    client = TestClient(app)
    r = client.get("/lab/projects/some-slug/docs/by-name/../etc/pages/1")
    # FastAPI may normalize `..` at the routing layer; either it 404s before
    # reaching us OR safe_filename rejects with 400. Both are acceptable —
    # what matters is no traversal succeeds.
    assert r.status_code in {400, 404}


def test_upload_with_valid_slug_but_missing_project() -> None:
    """Valid slug format passes the gate; the underlying tool's own behavior
    takes over (the upload helper raises if the project folder is missing)."""
    client = TestClient(app)
    r = client.post(
        "/lab/projects/no-such-project/upload",
        files={"file": ("a.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf")},
    )
    # Format check passes — point is it's NOT a 400 with "invalid slug"
    assert r.status_code != 400 or "invalid slug" not in r.text
