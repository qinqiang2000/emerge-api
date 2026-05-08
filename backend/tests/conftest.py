import os
from pathlib import Path

import pytest


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Isolated workspace root for each test."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture(autouse=True)
def env_isolation(monkeypatch: pytest.MonkeyPatch, workspace: Path) -> None:
    """Point EMERGE_WORKSPACE_ROOT at the per-test workspace."""
    monkeypatch.setenv("EMERGE_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("EMERGE_ANTHROPIC_API_KEY", "sk-test-not-used")
