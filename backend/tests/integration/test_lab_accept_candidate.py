import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.projects import create_project
from app.tools.schema import write_schema
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import candidate_dir, candidate_turn_path, prompt_path


async def test_get_schema_returns_current(workspace: Path) -> None:
    pid = await create_project(workspace, name="t")
    await write_schema(
        workspace, pid,
        [SchemaField(name="invoice_no", type=FieldType.STRING, description="d")],
        reason="seed", allow_structural=True,
    )
    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}/schema")
    assert r.status_code == 200
    fields = r.json()
    assert fields[0]["name"] == "invoice_no"


async def test_accept_candidate_overwrites_schema(workspace: Path) -> None:
    pid = await create_project(workspace, name="t")
    await write_schema(
        workspace, pid,
        [SchemaField(name="invoice_no", type=FieldType.STRING, description="OLD")],
        reason="seed", allow_structural=True,
    )
    job_id = "j_aaaaaaaaaaaa"
    candidate_dir(workspace, pid, job_id).mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        candidate_turn_path(workspace, pid, job_id, 3),
        {
            "turn": 3, "parent_turn": 0,
            "schema": [{"name": "invoice_no", "type": "string", "description": "NEW"}],
            "rationale": "tightened",
            "macro_f1": 0.92, "per_field": [], "predictions": {}, "ts": "t",
        },
    )
    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{pid}/schema/accept-candidate",
        json={"job_id": job_id, "turn": 3},
    )
    assert r.status_code == 200
    pv = json.loads(prompt_path(workspace, pid, "pr_baseline").read_text())
    assert pv["schema"][0]["description"] == "NEW"


async def test_accept_candidate_404_on_missing_candidate(workspace: Path) -> None:
    pid = await create_project(workspace, name="t")
    await write_schema(
        workspace, pid,
        [SchemaField(name="x", type=FieldType.STRING, description="d")],
        reason="seed", allow_structural=True,
    )
    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{pid}/schema/accept-candidate",
        json={"job_id": "j_nonexistenta", "turn": 1},
    )
    assert r.status_code == 404


async def test_accept_candidate_rejects_structural_diff(workspace: Path) -> None:
    """If a malformed candidate file tries to add a new field, reject."""
    pid = await create_project(workspace, name="t")
    await write_schema(
        workspace, pid,
        [SchemaField(name="x", type=FieldType.STRING, description="d")],
        reason="seed", allow_structural=True,
    )
    job_id = "j_aaaaaaaaaaaa"
    candidate_dir(workspace, pid, job_id).mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        candidate_turn_path(workspace, pid, job_id, 1),
        {
            "turn": 1, "parent_turn": 0,
            "schema": [
                {"name": "x", "type": "string", "description": "d"},
                {"name": "snuck_in", "type": "string", "description": "e"},
            ],
            "rationale": "bad", "macro_f1": 0.5, "per_field": [],
            "predictions": {}, "ts": "t",
        },
    )
    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{pid}/schema/accept-candidate",
        json={"job_id": job_id, "turn": 1},
    )
    assert r.status_code == 400
