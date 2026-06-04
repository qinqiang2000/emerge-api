"""Tenant-mode end-to-end: auth gate + per-team workspace isolation + headless
PAT parity. This is the crown-jewel proof for the Users & Teams milestone —
it exercises the whole T2+T3+T4 stack through the real HTTP app.

Open mode (no users) is covered implicitly by the rest of the suite, which
never creates a user and still passes flat/unauthenticated.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import store
from app.main import app
from app.workspace.paths import team_workspace_dir


async def _seed_superuser_and_team(root: Path, team_name: str) -> str:
    """Create the superuser (flips the platform into tenant mode) + a team.
    Returns the team's invite token."""
    su = await store.create_user(root, email="root@emerge.dev", password="x", is_superuser=True)
    team = await store.create_team(root, name=team_name, created_by=su.id)
    return team.invite_token


def _signup(client: TestClient, email: str, token: str) -> dict:
    r = client.post("/auth/signup", json={
        "email": email, "password": "pw", "full_name": email.split("@")[0], "token": token,
    })
    assert r.status_code == 200, r.text
    return r.json()


async def test_unauthenticated_lab_call_is_401_in_tenant_mode(workspace: Path) -> None:
    await _seed_superuser_and_team(workspace, "Honor")
    client = TestClient(app)  # no cookie
    r = client.get("/lab/projects")
    assert r.status_code == 401
    assert r.json()["detail"]["error_code"] == "not_authenticated"


async def test_signup_then_create_project_lands_in_team_dir(workspace: Path) -> None:
    token = await _seed_superuser_and_team(workspace, "Honor")
    client = TestClient(app)
    body = _signup(client, "dev@honor.com", token)
    team_dir = body["active_team"]["slug"]
    assert team_dir == "honor"  # human-readable dir, not the t_… id

    # session cookie now carried by the client → create a project
    r = client.post("/lab/projects", json={"name": "invoices"})
    assert r.status_code == 200, r.text
    slug = r.json()["slug"]

    # physical isolation: project.json lives UNDER teams/{slug}/, not at root
    assert (team_workspace_dir(workspace, team_dir) / slug / "project.json").exists()
    assert not (workspace / slug / "project.json").exists()

    # the team's project list shows it
    r = client.get("/lab/projects")
    assert r.status_code == 200
    assert [p["slug"] for p in r.json()] == [slug]


async def test_two_teams_cannot_see_each_others_projects(workspace: Path) -> None:
    su = await store.create_user(workspace, email="root@emerge.dev", password="x", is_superuser=True)
    honor = await store.create_team(workspace, name="Honor", created_by=su.id)
    huawei = await store.create_team(workspace, name="Huawei", created_by=su.id)

    c1 = TestClient(app)
    _signup(c1, "a@honor.com", honor.invite_token)
    c1.post("/lab/projects", json={"name": "honor-proj"})

    c2 = TestClient(app)
    _signup(c2, "b@huawei.com", huawei.invite_token)
    c2.post("/lab/projects", json={"name": "huawei-proj"})

    s1 = {p["slug"] for p in c1.get("/lab/projects").json()}
    s2 = {p["slug"] for p in c2.get("/lab/projects").json()}
    assert s1 == {"honor-proj"}
    assert s2 == {"huawei-proj"}
    # cross-team direct access → 404 (physical dir isolation, not 403)
    assert c1.get("/lab/projects/huawei-proj").status_code == 404


async def test_headless_pat_has_same_access_as_browser(workspace: Path) -> None:
    token = await _seed_superuser_and_team(workspace, "Honor")
    browser = TestClient(app)
    _signup(browser, "dev@honor.com", token)
    browser.post("/lab/projects", json={"name": "shared-proj"})

    # mint a PAT through the browser session
    pat = browser.post("/auth/me/tokens", json={"label": "cli"}).json()["token"]

    # a fresh client with NO cookie, only the bearer header, sees the same data
    headless = TestClient(app)
    r = headless.get("/lab/projects", headers={"Authorization": f"Bearer {pat}"})
    assert r.status_code == 200, r.text
    assert [p["slug"] for p in r.json()] == ["shared-proj"]
    # without the header → 401
    assert headless.get("/lab/projects").status_code == 401


async def test_invalid_invite_token_rejected(workspace: Path) -> None:
    await _seed_superuser_and_team(workspace, "Honor")
    client = TestClient(app)
    r = client.post("/auth/signup", json={
        "email": "x@y.com", "password": "pw", "full_name": "x", "token": "bogus",
    })
    assert r.status_code == 400
    assert r.json()["detail"]["error_code"] == "invalid_invite"


async def test_me_reports_open_mode_when_no_users(workspace: Path) -> None:
    # no superuser seeded → open mode
    client = TestClient(app)
    r = client.get("/auth/me")
    assert r.status_code == 200
    assert r.json() == {
        "authenticated": False, "open_mode": True,
        "user": None, "active_team": None, "teams": [],
    }
