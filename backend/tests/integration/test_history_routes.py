"""HTTP form of the history tools — confirms route wiring (param names, current_ws
binding) end-to-end in open mode. Skipped without git."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.workspace import history as history_lib

pytestmark = pytest.mark.skipif(not history_lib.git_available(), reason="git not on PATH")


def test_history_routes_log_diff_restore(workspace: Path) -> None:
    # Open mode (no users) → current_ws() == flat root == this test workspace.
    history_lib.ensure_repo(workspace)
    notes = workspace / "p" / "global_notes.md"
    notes.parent.mkdir(parents=True, exist_ok=True)
    # Real project (has project.json) so startup orphan-cleanup leaves it be.
    (workspace / "p" / "project.json").write_text('{"slug": "p"}', encoding="utf-8")
    notes.write_text("old\n", encoding="utf-8")
    v1 = history_lib.commit_all(workspace, "v1")
    notes.write_text("new\n", encoding="utf-8")
    history_lib.commit_all(workspace, "v2")
    assert v1

    with TestClient(app) as client:  # context manager → lifespan runs
        # log
        r = client.get("/lab/history", params={"slug": "p"})
        assert r.status_code == 200, r.text
        msgs = [v["message"] for v in r.json()["versions"]]
        assert "v1" in msgs and "v2" in msgs

        # diff v1 → current
        r = client.get("/lab/history/diff", params={"a": v1, "slug": "p"})
        assert r.status_code == 200, r.text
        assert "+new" in r.json()["diff"]

        # restore back to v1
        r = client.post("/lab/history/restore", json={"ref": v1, "slug": "p"})
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True
        assert notes.read_text() == "old\n"
