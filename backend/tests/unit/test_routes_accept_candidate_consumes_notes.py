# backend/tests/unit/test_routes_accept_candidate_consumes_notes.py
"""Phase B `accept_candidate` route side-effect: writes `_notes_consumed`
entries on the reviewed files corresponding to `notes_hit` in the candidate
JSON.

Verifies:
    * Reviewed file `_notes_consumed` entries land with the correct shape
      (consumed_via='accept_candidate', source_ref="j_x.turn_n",
      active_prompt_id=<active>).
    * Entities + _notes text are NOT touched (only the sibling map).
    * notes_hit entries pointing to fields without an inline `_note` are
      gracefully skipped (no phantom entry).
    * Empty notes_hit → no reviewed mutation at all.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.projects import create_project
from app.tools.reviewed import save_reviewed
from app.tools.schema import write_schema
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import candidate_turn_path, reviewed_path


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("EMERGE_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("EMERGE_TEST_MODE", "1")
    return TestClient(app)


async def _seed_project_with_reviewed(
    workspace: Path,
    *,
    name: str,
    schema_fields: list[SchemaField],
    reviewed_filename: str,
    reviewed_entities: list[dict],
    reviewed_notes: dict[str, str],
) -> str:
    """Create a project with a baseline prompt + one reviewed file."""
    out = await create_project(workspace, name=name)
    slug = out["slug"]
    await write_schema(
        workspace, slug, schema_fields,
        reason="seed", allow_structural=True,
    )
    await save_reviewed(
        workspace, slug, reviewed_filename,
        entities=reviewed_entities,
        notes=reviewed_notes,
    )
    return slug


def _seed_candidate(workspace: Path, slug: str, job_id: str, turn: int, candidate_blob: dict) -> None:
    target = candidate_turn_path(workspace, slug, job_id, turn)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(target, candidate_blob)


async def test_accept_candidate_writes_notes_consumed(
    client: TestClient, tmp_path: Path,
) -> None:
    slug = await _seed_project_with_reviewed(
        tmp_path,
        name="acc-test",
        schema_fields=[
            SchemaField(name="buyer_name", type=FieldType.STRING, description="seller party"),
            SchemaField(name="seller_name", type=FieldType.STRING, description="buyer party"),
        ],
        reviewed_filename="inv-042.pdf",
        reviewed_entities=[{"buyer_name": "ACME", "seller_name": "X"}],
        reviewed_notes={"buyer_name": "should be ACME Sdn Bhd"},
    )
    # Candidate JSON: same shape as a real autoresearch turn's output, with a
    # description-change on `buyer_name` and matching notes_hit.
    job_id = "j_aaaaaaaaaaaa"
    turn = 4
    candidate_blob = {
        "turn": turn,
        "parent_turn": 0,
        "schema": [
            {"name": "buyer_name", "type": "string",
             "description": "seller party — official Sdn Bhd suffix preferred", "required": True},
            {"name": "seller_name", "type": "string", "description": "buyer party", "required": True},
        ],
        "rationale": "tightened",
        "macro_f1": 0.9,
        "per_field": [],
        "predictions": {},
        "ts": "2026-05-16T10:00:00Z",
        "notes_hit": ["inv-042.pdf.buyer_name"],
        "notes_hit_filtered": [],
    }
    _seed_candidate(tmp_path, slug, job_id, turn, candidate_blob)

    resp = client.post(
        f"/lab/projects/{slug}/schema/accept-candidate",
        json={"job_id": job_id, "turn": turn},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body.get("notes_consumed") == {"inv-042.pdf": ["buyer_name"]}

    # Reviewed file got a consumption record.
    blob = json.loads(reviewed_path(tmp_path, slug, "inv-042.pdf").read_text())
    assert "_notes_consumed" in blob
    consumed = blob["_notes_consumed"]["buyer_name"]
    assert consumed["consumed_via"] == "accept_candidate"
    assert consumed["source_ref"] == f"{job_id}.turn_{turn}"
    assert consumed["active_prompt_id"]  # non-empty — anchored to the active prompt
    # Entities and original notes text untouched.
    assert blob["entities"][0]["buyer_name"] == "ACME"
    assert blob["_notes"]["buyer_name"] == "should be ACME Sdn Bhd"


async def test_accept_candidate_skips_phantom_consumption(
    client: TestClient, tmp_path: Path,
) -> None:
    """If notes_hit references a field that has no `_note` in the reviewed
    file, the route must NOT write a phantom consumption entry."""
    slug = await _seed_project_with_reviewed(
        tmp_path,
        name="phantom",
        schema_fields=[
            SchemaField(name="buyer_name", type=FieldType.STRING, description="party A"),
        ],
        reviewed_filename="inv-001.pdf",
        reviewed_entities=[{"buyer_name": "ACME"}],
        reviewed_notes={},  # no inline notes at all
    )
    job_id = "j_aaaaaaaaaaaa"
    turn = 1
    _seed_candidate(tmp_path, slug, job_id, turn, {
        "turn": turn, "parent_turn": 0,
        "schema": [{"name": "buyer_name", "type": "string", "description": "party A revised"}],
        "rationale": "x", "macro_f1": 0.9, "per_field": [],
        "predictions": {}, "ts": "t",
        "notes_hit": ["inv-001.pdf.buyer_name"],
    })
    resp = client.post(
        f"/lab/projects/{slug}/schema/accept-candidate",
        json={"job_id": job_id, "turn": turn},
    )
    assert resp.status_code == 200
    body = resp.json()
    # No reviewed file actually had this note → no consumption recorded.
    assert body.get("notes_consumed") in (None, {}, {"inv-001.pdf": []})

    blob = json.loads(reviewed_path(tmp_path, slug, "inv-001.pdf").read_text())
    assert "_notes_consumed" not in blob


async def test_accept_candidate_with_no_notes_hit_does_not_touch_reviewed(
    client: TestClient, tmp_path: Path,
) -> None:
    slug = await _seed_project_with_reviewed(
        tmp_path,
        name="nohit",
        schema_fields=[
            SchemaField(name="buyer_name", type=FieldType.STRING, description="x"),
        ],
        reviewed_filename="inv-001.pdf",
        reviewed_entities=[{"buyer_name": "ACME"}],
        reviewed_notes={"buyer_name": "active hint"},
    )
    job_id = "j_aaaaaaaaaaaa"
    turn = 1
    _seed_candidate(tmp_path, slug, job_id, turn, {
        "turn": turn, "parent_turn": 0,
        "schema": [{"name": "buyer_name", "type": "string", "description": "x — updated"}],
        "rationale": "r", "macro_f1": 0.9, "per_field": [],
        "predictions": {}, "ts": "t",
        # No notes_hit at all.
    })
    resp = client.post(
        f"/lab/projects/{slug}/schema/accept-candidate",
        json={"job_id": job_id, "turn": turn},
    )
    assert resp.status_code == 200
    blob = json.loads(reviewed_path(tmp_path, slug, "inv-001.pdf").read_text())
    assert "_notes_consumed" not in blob
    # Notes still intact.
    assert blob["_notes"]["buyer_name"] == "active hint"
