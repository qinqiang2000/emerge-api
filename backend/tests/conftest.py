import os
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.provider.base import Provider, ProviderResult


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Isolated workspace root for each test."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture(autouse=True)
def env_isolation(monkeypatch: pytest.MonkeyPatch, workspace: Path) -> None:
    """Point EMERGE_WORKSPACE_ROOT at the per-test workspace, stub auth, and
    isolate Settings from the dev `.env` file.

    Pydantic-settings's `env_file=".env"` (see `app/config.py`) resolves
    against cwd at every `Settings()` construction. When tests run from
    `backend/`, the developer's `.env` bleeds into every test that uses
    `get_settings()` — `monkeypatch.delenv` only touches the process env,
    not the file. Chdir to the per-test workspace so no `.env` is in scope.
    """
    monkeypatch.setenv("EMERGE_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("GOOGLE_API_KEY", "google-test-not-used")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test-not-used")
    monkeypatch.chdir(workspace)


@pytest.fixture
def stub_provider() -> AsyncMock:
    """An AsyncMock implementing the Provider protocol. Tests set return_value."""
    mock = AsyncMock(spec=Provider)
    return mock


def make_provider_result(payload: dict[str, Any], model_id: str = "stub") -> ProviderResult:
    return ProviderResult(raw_json=payload, model_id=model_id, input_tokens=0, output_tokens=0)
