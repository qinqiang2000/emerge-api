from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.tools.docs import upload_doc
from app.tools.projects import create_project


_FIXTURE = Path(__file__).parent.parent / "fixtures" / "invoice_sample.pdf"


async def test_get_page_returns_png(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    meta = await upload_doc(workspace, pid, _FIXTURE.read_bytes(), "sample.pdf")
    client = TestClient(app)
    # filename is path-encoded as the doc handle (post-d_xxx). The route uses
    # `{filename:path}` so the encoded slug flows through to safe_filename().
    r = client.get(f"/lab/projects/{pid}/docs/by-name/{meta['filename']}/pages/1")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


async def test_get_page_404_for_missing(workspace: Path) -> None:
    client = TestClient(app)
    r = client.get("/lab/projects/p_doesnotexist/docs/by-name/nope.pdf/pages/1")
    assert r.status_code == 404
