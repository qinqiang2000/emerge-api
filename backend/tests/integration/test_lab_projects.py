from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.tools.projects import create_project


async def test_list_projects_returns_created(workspace: Path) -> None:
    pid = await create_project(workspace, name="inv-MY")
    client = TestClient(app)
    r = client.get("/lab/projects")
    assert r.status_code == 200
    items = r.json()
    assert any(it["project_id"] == pid for it in items)


async def test_get_one_project(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}")
    assert r.status_code == 200
    assert r.json()["name"] == "x"


def test_get_unknown_project_404() -> None:
    client = TestClient(app)
    r = client.get("/lab/projects/p_doesnotexist")
    assert r.status_code == 404


async def test_get_project_docs_with_status(workspace: Path) -> None:
    from app.tools.docs import upload_doc
    from app.tools.reviewed import save_reviewed
    from app.schemas.reviewed import ReviewedSource

    pid = await create_project(workspace, name="x")
    pdf = b"%PDF-1.4\n%%EOF\n"
    d1 = await upload_doc(workspace, pid, pdf, "a.pdf")
    d2 = await upload_doc(workspace, pid, pdf, "b.pdf")
    # mark one reviewed
    await save_reviewed(
        workspace, pid, d1, entities=[{}], source=ReviewedSource.MANUAL
    )

    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}/docs")
    assert r.status_code == 200
    items = r.json()
    by_id = {it["doc_id"]: it for it in items}
    assert by_id[d1]["has_reviewed"] is True
    assert by_id[d1]["has_prediction"] is False
    assert by_id[d2]["has_reviewed"] is False
    assert by_id[d2]["filename"] == "b.pdf"


def test_get_project_docs_400_on_bad_pid() -> None:
    client = TestClient(app)
    r = client.get("/lab/projects/p_INVALIDPATH/docs")
    assert r.status_code == 400


async def test_get_project_schema(workspace: Path) -> None:
    from app.tools.schema import write_schema
    from app.schemas.schema_field import FieldType, SchemaField

    pid = await create_project(workspace, name="x")
    await write_schema(
        workspace,
        pid,
        [SchemaField(name="invoice_no", type=FieldType.STRING, description="d")],
        reason="seed",
        allow_structural=True,
    )
    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}/schema")
    assert r.status_code == 200
    fields = r.json()
    assert len(fields) == 1
    assert fields[0]["name"] == "invoice_no"


def test_get_project_schema_400_on_bad_pid() -> None:
    client = TestClient(app)
    r = client.get("/lab/projects/p_INVALIDPATH/schema")
    assert r.status_code == 400


async def test_list_projects_includes_status(workspace: Path) -> None:
    from app.tools.projects import list_projects, update_project
    from app.tools.schema import write_schema
    from app.schemas.schema_field import FieldType, SchemaField

    ws = workspace
    p_empty = await create_project(ws, name="empty-one")
    p_draft = await create_project(ws, name="draft-one")
    await write_schema(
        ws,
        p_draft,
        [SchemaField(name="f", type=FieldType.STRING, description="d")],
        reason="t",
        allow_structural=True,
    )
    rows = {r["project_id"]: r for r in await list_projects(ws)}
    assert rows[p_empty]["status"] == "empty"
    assert rows[p_draft]["status"] == "draft"
    # 'live' requires an active_version_id — set it directly on the blob.
    await update_project(ws, p_draft, {"active_version_id": "v1"})
    rows = {r["project_id"]: r for r in await list_projects(ws)}
    assert rows[p_draft]["status"] == "live"
