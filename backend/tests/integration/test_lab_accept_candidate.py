import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.projects import create_project
from app.tools.prompt import list_prompts, read_active_prompt, write_prompt
from app.tools.schema import write_schema
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    candidate_dir,
    candidate_turn_path,
    project_json_path,
    prompt_path,
)


async def test_get_schema_returns_current(workspace: Path) -> None:
    pid = (await create_project(workspace, name="t"))["slug"]
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


async def test_accept_candidate_mints_new_variant(workspace: Path) -> None:
    """Accept no longer mutates the active prompt in place — it mints a new
    PromptVariant (lineage via derived_from), overwrites its schema with the
    candidate, and switches active to it. The prior variant is left untouched
    (rollback = switch back)."""
    pid = (await create_project(workspace, name="t"))["slug"]
    await write_schema(
        workspace, pid,
        [SchemaField(name="invoice_no", type=FieldType.STRING, description="OLD")],
        reason="seed", allow_structural=True,
        global_notes="keep me",
    )
    job_id = "j_aaaaaaaaaaaa"
    candidate_dir(workspace, pid, job_id).mkdir(parents=True, exist_ok=True)
    # turn_0 baseline (for the delta in the label) + the improving turn_3.
    atomic_write_json(
        candidate_turn_path(workspace, pid, job_id, 0),
        {
            "turn": 0, "parent_turn": None,
            "schema": [{"name": "invoice_no", "type": "string", "description": "OLD"}],
            "rationale": "baseline",
            "field_accuracy_macro": 0.80, "macro_f1": 0.80,
            "per_field": [], "predictions": {}, "ts": "t",
        },
    )
    atomic_write_json(
        candidate_turn_path(workspace, pid, job_id, 3),
        {
            "turn": 3, "parent_turn": 0,
            "schema": [{"name": "invoice_no", "type": "string", "description": "NEW"}],
            "rationale": "tightened",
            "field_accuracy_macro": 0.92, "macro_f1": 0.92,
            "per_field": [], "predictions": {}, "ts": "t",
        },
    )
    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{pid}/schema/accept-candidate",
        json={"job_id": job_id, "turn": 3},
    )
    assert r.status_code == 200
    payload = r.json()
    new_id = payload["new_prompt_id"]
    assert new_id and new_id != "pr_baseline"
    # Delta surfaced in the response (0.92 - 0.80 ≈ 0.12).
    assert payload["field_accuracy_macro"] == 0.92
    assert payload["delta"] == 0.92 - 0.80

    # Prior variant untouched (rollback target).
    old = json.loads(prompt_path(workspace, pid, "pr_baseline").read_text())
    assert old["schema"][0]["description"] == "OLD"

    # New variant: carries the candidate's NEW description, preserves
    # global_notes, records lineage, and is the active prompt.
    active = await read_active_prompt(workspace, pid)
    assert active.prompt_id == new_id
    assert active.schema[0].description == "NEW"
    assert active.global_notes == "keep me"
    assert active.derived_from == "pr_baseline"

    # list_prompts surfaces the new variant with its lineage.
    rows = await list_prompts(workspace, pid)
    by_id = {row["prompt_id"]: row for row in rows}
    assert new_id in by_id
    assert by_id[new_id]["derived_from"] == "pr_baseline"
    assert by_id[new_id]["is_active"] is True
    # Label carries the date + the rounded delta percentage point.
    assert by_id[new_id]["label"].startswith("tune ")
    assert "+12%" in by_id[new_id]["label"]


async def test_accept_candidate_resets_correction_counter(workspace: Path) -> None:
    """Accepting a candidate zeroes `corrections_since_tune` (the backlog that
    motivated the tune is now folded into the new variant)."""
    pid = (await create_project(workspace, name="t"))["slug"]
    await write_schema(
        workspace, pid,
        [SchemaField(name="invoice_no", type=FieldType.STRING, description="OLD")],
        reason="seed", allow_structural=True,
    )
    # Seed a non-zero counter directly on project.json.
    pj = project_json_path(workspace, pid)
    blob = json.loads(pj.read_text())
    blob["corrections_since_tune"] = 7
    pj.write_text(json.dumps(blob))

    job_id = "j_bbbbbbbbbbbb"
    candidate_dir(workspace, pid, job_id).mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        candidate_turn_path(workspace, pid, job_id, 1),
        {
            "turn": 1, "parent_turn": 0,
            "schema": [{"name": "invoice_no", "type": "string", "description": "NEW"}],
            "rationale": "tightened",
            "field_accuracy_macro": 0.90, "macro_f1": 0.90,
            "per_field": [], "predictions": {}, "ts": "t",
        },
    )
    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{pid}/schema/accept-candidate",
        json={"job_id": job_id, "turn": 1},
    )
    assert r.status_code == 200
    blob = json.loads(pj.read_text())
    assert blob["corrections_since_tune"] == 0


async def test_accept_candidate_anchors_notes_consumed_to_new_variant(workspace: Path) -> None:
    """notes_consumed runs AFTER the active switch, so its active_prompt_id
    anchor is the freshly-minted variant, not the old one."""
    from app.tools.reviewed import get_reviewed, save_reviewed

    pid = (await create_project(workspace, name="t"))["slug"]
    await write_schema(
        workspace, pid,
        [SchemaField(name="buyer_name", type=FieldType.STRING, description="OLD")],
        reason="seed", allow_structural=True,
    )
    # A reviewed file with an inline note on buyer_name.
    await save_reviewed(
        workspace, pid, "inv-001.pdf",
        entities=[{"buyer_name": "ACME"}],
        notes={"buyer_name": "official: ACME Sdn Bhd"},
    )
    job_id = "j_cccccccccccc"
    candidate_dir(workspace, pid, job_id).mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        candidate_turn_path(workspace, pid, job_id, 2),
        {
            "turn": 2, "parent_turn": 0,
            "schema": [{"name": "buyer_name", "type": "string", "description": "NEW"}],
            "rationale": "folded note",
            "field_accuracy_macro": 0.90, "macro_f1": 0.90,
            "per_field": [], "predictions": {}, "ts": "t",
            "notes_hit": ["inv-001.pdf.buyer_name"],
        },
    )
    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{pid}/schema/accept-candidate",
        json={"job_id": job_id, "turn": 2},
    )
    assert r.status_code == 200
    new_id = r.json()["new_prompt_id"]
    reviewed = await get_reviewed(workspace, pid, "inv-001.pdf")
    assert reviewed is not None
    consumed = reviewed["_notes_consumed"]["buyer_name"]
    assert consumed["active_prompt_id"] == new_id
    assert consumed["source_ref"] == f"{job_id}.turn_2"


async def test_accept_candidate_404_on_missing_candidate(workspace: Path) -> None:
    pid = (await create_project(workspace, name="t"))["slug"]
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
    pid = (await create_project(workspace, name="t"))["slug"]
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
