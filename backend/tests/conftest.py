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
    """Point EMERGE_WORKSPACE_ROOT at the per-test workspace."""
    monkeypatch.setenv("EMERGE_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("EMERGE_ANTHROPIC_API_KEY", "sk-test-not-used")


@pytest.fixture
def stub_provider() -> AsyncMock:
    """An AsyncMock implementing the Provider protocol. Tests set return_value."""
    mock = AsyncMock(spec=Provider)
    return mock


def make_provider_result(payload: dict[str, Any], model_id: str = "stub") -> ProviderResult:
    return ProviderResult(raw_json=payload, model_id=model_id, input_tokens=0, output_tokens=0)
