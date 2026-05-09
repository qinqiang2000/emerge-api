from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.jobs.runner import JobRunner
from app.provider.base import Provider


_runner: Optional[JobRunner] = None


def get_runner(*, workspace: Path, provider: Provider, model_id: str) -> JobRunner:
    """Return the process-wide JobRunner. First call creates it; subsequent
    calls return the same instance regardless of args."""
    global _runner
    if _runner is None:
        _runner = JobRunner(workspace=workspace, provider=provider, model_id=model_id)
    return _runner


def reset_runner_for_tests() -> None:
    """Test-only: drop the cached singleton so the next get_runner re-creates."""
    global _runner
    _runner = None
