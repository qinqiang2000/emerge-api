"""Filesystem-over-MCP — containment is the security boundary (plan
2026-06-09-filesystem-over-mcp.md). These lock the path guard (traversal,
symlink-escape, secret denylist, cross-team) and the read-side behaviour.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.tools import workspace_fs as wfs
from app.tools.workspace_fs import WsPathError, _safe_ws_path


@pytest.fixture
def team_ws(tmp_path: Path) -> Path:
    """A team workspace with one project laid out like the real thing."""
    ws = tmp_path / "teams" / "acme"
    proj = ws / "us-invoice"
    (proj / "models").mkdir(parents=True)
    (proj / "project.json").write_text('{"name":"US Invoice","active_model_id":"m_abc"}')
    (proj / "models" / "m_abc.json").write_text('{"provider_model_id":"gemini-2.5-flash"}')
    (proj / "_chats").mkdir()  # sentinel — must be hidden
    (proj / ".secret").write_text("nope")  # dotfile — hidden
    return ws


# --- containment ------------------------------------------------------------

def test_safe_path_allows_inside(team_ws: Path) -> None:
    p = _safe_ws_path(team_ws, "us-invoice/project.json")
    assert p == (team_ws / "us-invoice" / "project.json").resolve()


def test_safe_path_rejects_parent_traversal(team_ws: Path) -> None:
    with pytest.raises(WsPathError):
        _safe_ws_path(team_ws, "../other-team/secrets.json")
    with pytest.raises(WsPathError):
        _safe_ws_path(team_ws, "us-invoice/../../escape")


def test_safe_path_rejects_absolute_escape(team_ws: Path) -> None:
    with pytest.raises(WsPathError):
        _safe_ws_path(team_ws, "/etc/passwd")


def test_safe_path_rejects_symlink_escape(team_ws: Path, tmp_path: Path) -> None:
    secret = tmp_path / "outside.txt"
    secret.write_text("leak")
    link = team_ws / "us-invoice" / "link"
    link.symlink_to(secret)
    with pytest.raises(WsPathError):
        _safe_ws_path(team_ws, "us-invoice/link")


def test_safe_path_blocks_secret_denylist(team_ws: Path) -> None:
    # even if such a file landed inside a team dir, the denylist refuses it
    for bad in ("us-invoice/.env", "us-invoice/foo.key", "us-invoice/my.pem",
                "us-invoice/api_secret.txt", "_auth/users.json", "_keys.json"):
        with pytest.raises(WsPathError):
            _safe_ws_path(team_ws, bad)


# --- ws_list ----------------------------------------------------------------

def test_ws_list_root_shows_projects(team_ws: Path) -> None:
    out = wfs.ws_list(team_ws, ".")
    names = {e["name"] for e in out["entries"]}
    assert "us-invoice" in names


def test_ws_list_hides_sentinels_and_dotfiles(team_ws: Path) -> None:
    out = wfs.ws_list(team_ws, "us-invoice")
    names = {e["name"] for e in out["entries"]}
    assert "models" in names and "project.json" in names
    assert "_chats" not in names and ".secret" not in names


def test_ws_list_models_dir(team_ws: Path) -> None:
    # the screenshot's flail: the agent needs to see models/ contents
    out = wfs.ws_list(team_ws, "us-invoice/models")
    assert {e["name"] for e in out["entries"]} == {"m_abc.json"}


# --- ws_read ----------------------------------------------------------------

def test_ws_read_project_json(team_ws: Path) -> None:
    out = wfs.ws_read(team_ws, "us-invoice/project.json")
    assert "active_model_id" in out["content"]


def test_ws_read_binary_refused(team_ws: Path) -> None:
    (team_ws / "us-invoice" / "scan.pdf").write_bytes(b"%PDF-1.4\x00\xff\xfe binary")
    out = wfs.ws_read(team_ws, "us-invoice/scan.pdf")
    assert "read_doc_image" in out["error"]


def test_ws_read_blocked_secret_raises(team_ws: Path) -> None:
    (team_ws / "us-invoice" / ".env").write_text("GOOGLE_API_KEY=leak")
    with pytest.raises(WsPathError):
        wfs.ws_read(team_ws, "us-invoice/.env")


# --- ws_grep ----------------------------------------------------------------

def test_ws_grep_finds_model_id(team_ws: Path) -> None:
    out = wfs.ws_grep(team_ws, "gemini-2.5-flash")
    hits = {m["file"] for m in out["matches"]}
    assert "us-invoice/models/m_abc.json" in hits


def test_ws_grep_skips_hidden(team_ws: Path) -> None:
    out = wfs.ws_grep(team_ws, "nope")  # ".secret" contains "nope"
    assert out["matches"] == []
