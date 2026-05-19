"""HTTP coverage for the M11 Phase B T11 lab routes on publish.py:

* `POST /lab/projects/{slug}/versions/freeze` — wraps `freeze_version`
* `POST /lab/keys` — wraps `issue_api_key`, returns one-time plaintext

These mirror what the tools already do; the routes are thin wrappers so a
CLI agent driving HTTP has parity with the in-session agent's tool surface.

The one-time-reveal contract on `POST /lab/keys` is load-bearing: the
plaintext appears in this response and never again — `GET /lab/keys/meta`
must NOT surface it after issue.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.projects import create_project
from app.tools.schema import write_schema
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    predictions_draft_dir,
    project_json_path,
    reviewed_dir,
    version_path,
)


async def _seed_ready_to_publish(workspace: Path, name: str = "freeze-test") -> str:
    """Mint a project + write schema + drop 3 reviewed/prediction pairs so
    readiness's hard gates all pass. Mirrors `_seed_for_publish` in
    `test_lab_publish_e2e.py` (kept local to avoid cross-test import)."""
    slug = (await create_project(workspace, name=name))["slug"]
    await write_schema(
        workspace, slug,
        [
            SchemaField(name="buyer_name", type=FieldType.STRING, description="x"),
            SchemaField(name="total_amount", type=FieldType.NUMBER, description="x"),
        ],
        reason="seed", allow_structural=True,
    )
    reviewed_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    predictions_draft_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    for i in range(3):
        did = f"doc{i}.pdf"
        atomic_write_json(
            reviewed_dir(workspace, slug) / f"{did}.json",
            {
                "entities": [{"buyer_name": "ACME", "total_amount": 100.0}],
                "source": "manual",
            },
        )
        atomic_write_json(
            predictions_draft_dir(workspace, slug) / f"{did}.json",
            {"entities": [{"buyer_name": "ACME", "total_amount": 100.0}]},
        )
    return slug


# ---------------------------------------------------------------------------
# POST /lab/projects/{slug}/versions/freeze
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_freeze_route_happy_path(workspace: Path) -> None:
    """Project ready → `{version_id, published_id}` and v1.json on disk."""
    slug = await _seed_ready_to_publish(workspace)
    client = TestClient(app)
    r = client.post(f"/lab/projects/{slug}/versions/freeze")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version_id"] == "v1"
    assert body["published_id"].startswith("pub_")
    assert version_path(workspace, slug, 1).exists()


@pytest.mark.asyncio
async def test_freeze_route_accepts_version_id_in_body(workspace: Path) -> None:
    """Body with explicit `version_id` is accepted but the module function
    auto-mints — the on-disk version is still `v1`. Body shape parity."""
    slug = await _seed_ready_to_publish(workspace, name="freeze-explicit")
    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{slug}/versions/freeze", json={"version_id": "v9"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Module function auto-mints — v1 since this is the first publish.
    assert body["version_id"] == "v1"
    assert body["published_id"].startswith("pub_")


@pytest.mark.asyncio
async def test_freeze_route_readiness_fail_envelope(workspace: Path) -> None:
    """Schema-empty project → readiness fails → structured 400 envelope
    (NOT a 500). The body carries `error_code='not_ready'` and `checks` so
    the caller can show the user which gates blocked."""
    slug = (await create_project(workspace, name="blank"))["slug"]
    client = TestClient(app)
    r = client.post(f"/lab/projects/{slug}/versions/freeze")
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert detail["error_code"] == "not_ready"
    assert "checks" in detail
    # At least one check must report fail (schema_non_empty).
    failed = [c for c in detail["checks"] if c["status"] == "fail"]
    assert failed
    assert any(c["key"] == "schema_non_empty" for c in failed)


def test_freeze_route_404_on_unknown_project() -> None:
    """Slug-shaped value that doesn't exist → structured 404 envelope."""
    client = TestClient(app)
    r = client.post("/lab/projects/does-not-exist/versions/freeze")
    assert r.status_code == 404, r.text
    assert r.json()["detail"]["error_code"] == "project_not_found"


@pytest.mark.asyncio
async def test_freeze_route_force_bypasses_readiness(workspace: Path) -> None:
    """`force=true` skips readiness gates — surfaces a v1 freeze even on
    a project that wouldn't normally pass. Mirrors the tool's `force`
    kwarg semantics."""
    slug = (await create_project(workspace, name="force-test"))["slug"]
    # Write minimum-viable schema so freeze_version itself doesn't choke
    # downstream when it reads the active prompt's fields.
    await write_schema(
        workspace, slug,
        [SchemaField(name="x", type=FieldType.STRING, description="x")],
        reason="seed", allow_structural=True,
    )
    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{slug}/versions/freeze", json={"force": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version_id"] == "v1"
    assert body["published_id"].startswith("pub_")


# ---------------------------------------------------------------------------
# POST /lab/keys  (one-time reveal)
# ---------------------------------------------------------------------------


def test_issue_key_route_happy_path_returns_plaintext() -> None:
    """Fresh issue → body carries `key_plaintext` + `key_hash` + `key_prefix`
    + `created_at`. The plaintext is the one-time reveal — no caller will
    see it again post-this-response."""
    client = TestClient(app)
    r = client.post("/lab/keys", json={"user_id": "default"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["key_plaintext"].startswith("ek_")
    assert body["key_hash"]
    assert body["key_prefix"].startswith("ek_")
    assert body["created_at"]
    assert body["user_id"] == "default"


def test_issue_key_route_accepts_audit_hints() -> None:
    """Body shape per the plan accepts `project_id` + `version_id` as audit
    hints. They're echoed back in the response but not load-bearing —
    keys are user-scoped post-slug-transparency."""
    client = TestClient(app)
    r = client.post(
        "/lab/keys",
        json={"project_id": "p_abcdef012345", "version_id": "v1"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["project_id"] == "p_abcdef012345"
    assert body["version_id"] == "v1"
    assert body["key_plaintext"].startswith("ek_")


def test_issue_key_plaintext_never_in_meta_post_issue() -> None:
    """One-time reveal contract: after `POST /lab/keys` returns the
    plaintext once, `GET /lab/keys/meta` exposes only the hash-short. The
    plaintext is NOT recoverable from the server."""
    client = TestClient(app)
    r1 = client.post("/lab/keys", json={"user_id": "default"})
    assert r1.status_code == 200, r1.text
    issued = r1.json()
    plaintext = issued["key_plaintext"]
    full_hash = issued["key_hash"]

    r2 = client.get("/lab/keys/meta")
    assert r2.status_code == 200, r2.text
    meta = r2.json()
    # The plaintext is never exposed via meta — only the hash short tail.
    assert "key_plaintext" not in meta
    assert plaintext not in r2.text
    assert meta["key_hash_short"] == full_hash[-6:]
    assert meta["created_at"]


def test_issue_key_route_rotation_replaces_prior_key() -> None:
    """Per-user-scope upsert: a second `POST /lab/keys` rotates — the new
    plaintext differs and the old hash short is replaced in meta."""
    client = TestClient(app)
    r1 = client.post("/lab/keys", json={"user_id": "default"})
    first = r1.json()
    r2 = client.post("/lab/keys", json={"user_id": "default"})
    second = r2.json()
    assert second["key_plaintext"] != first["key_plaintext"]
    r3 = client.get("/lab/keys/meta")
    meta = r3.json()
    # Meta tracks the live (rotated) key, not the prior one.
    assert meta["key_hash_short"] == second["key_hash"][-6:]
    assert meta["key_hash_short"] != first["key_hash"][-6:]


def test_issue_key_route_defaults_user_id_to_default() -> None:
    """Body without `user_id` should still issue against the single-user
    placeholder `"default"`. Mirrors the tool's default kwarg."""
    client = TestClient(app)
    r = client.post("/lab/keys", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_id"] == "default"
    assert body["key_plaintext"].startswith("ek_")


def test_issue_key_route_no_body() -> None:
    """Empty POST (no body at all) is accepted — same as `{}`. Belt-and-
    braces for CLI clients that POST without a content-type header."""
    client = TestClient(app)
    r = client.post("/lab/keys")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_id"] == "default"
    assert body["key_plaintext"].startswith("ek_")
