"""Plugin bundle integrity (P3 — plugin/ marketplace + emerge plugin).

The bundle under repo-root `plugin/` is a static distribution artifact (NOT
imported by the backend). These guards keep it valid and, crucially, keep its
hard-coded remote-connector URL in sync with the deployed prod origin so a domain
change can't leave teammates' installs silently pointing at a dead address.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# repo root = three up from this test file (backend/tests/unit/)
_REPO = Path(__file__).resolve().parents[3]
_PLUGIN = _REPO / "plugin" / "emerge"
_MARKETPLACE = _REPO / "plugin" / ".claude-plugin" / "marketplace.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_plugin_manifest_valid() -> None:
    manifest = _load(_PLUGIN / ".claude-plugin" / "plugin.json")
    assert manifest["name"] == "emerge"  # drives the /emerge:* namespace
    assert manifest["version"]
    assert manifest["description"]


def test_plugin_name_is_task_agnostic() -> None:
    """CLAUDE.md red line: chrome is task-type-agnostic. The plugin is a
    document-processing colleague, not an 'extractor' — name/displayName must not
    bake in extraction-only vocab (classification/matching come later)."""
    manifest = _load(_PLUGIN / ".claude-plugin" / "plugin.json")
    assert manifest["name"] == "emerge"
    assert "extract" not in manifest["name"].lower()
    assert "extract" not in manifest.get("displayName", "").lower()


def test_marketplace_references_plugin() -> None:
    mkt = _load(_MARKETPLACE)
    assert mkt["name"]
    entry = next(p for p in mkt["plugins"] if p["name"] == "emerge")
    src = (_MARKETPLACE.parent.parent / entry["source"]).resolve()
    assert src == _PLUGIN, f"marketplace source {entry['source']} != plugin dir"
    assert (src / ".claude-plugin" / "plugin.json").exists()


def test_mcp_url_matches_prod_origin() -> None:
    """The bundled remote-connector URL must equal the deployed prod origin +
    `/mcp/`. If prod's domain moves, update both `EMERGE_PUBLIC_BASE_URL` (in the
    deploy) AND this `.mcp.json`; this test red-flags drift between them."""
    PROD_ORIGIN = "https://fpydoc.duckdns.org"  # = Settings.public_base_url on prod
    mcp = _load(_PLUGIN / ".mcp.json")
    server = mcp["mcpServers"]["emerge"]
    assert server["type"] == "http"
    assert server["url"] == f"{PROD_ORIGIN}/mcp/"


def test_skill_has_description_frontmatter() -> None:
    """Model-invocation requires a `description` in the SKILL.md frontmatter."""
    text = (_PLUGIN / "skills" / "emerge" / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    fm = text.split("---\n", 2)[1]
    assert "description:" in fm
    # task-agnostic framing (CLAUDE.md): the skill must present emerge as more
    # than an extractor — classification/matching are first-class futures, so the
    # description names them rather than pinning to extraction only. (Doc-type
    # words like "invoice" are fine as model-invocation trigger hints.)
    low = fm.lower()
    assert "classif" in low and "match" in low


def test_commands_use_generic_verbs() -> None:
    """Commands are named with generic verbs (run/compare/tune/publish), not
    extraction-specific words like 'extract'."""
    cmd_dir = _PLUGIN / "commands"
    names = {p.stem for p in cmd_dir.glob("*.md")}
    assert names == {"run", "compare", "tune", "publish"}
    for md in cmd_dir.glob("*.md"):
        text = md.read_text(encoding="utf-8")
        assert text.startswith("---\n") and "description:" in text.split("---\n", 2)[1]
