from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.jobs.runner import JobRunner
from app.provider.base import Provider


_runner: Optional[JobRunner] = None


def get_runner(*, workspace: Path, provider: Provider) -> JobRunner:
    """Return the process-wide JobRunner. First call creates it; subsequent
    calls return the same instance regardless of args.

    Note: no `model_id` parameter — the proposer model is resolved per-job
    from the project's active ModelConfig (with override / env fallback) at
    `runner.start()` time. See `_resolve_proposer_model` in
    `app/jobs/autoresearch.py`. The previous design pinned an env-seeded
    model on the singleton, which silently bypassed `switch_active_model`
    for autoresearch — see `default-extract-model-prompts-ev-eager-turing`
    plan."""
    global _runner
    if _runner is None:
        _runner = JobRunner(workspace=workspace, provider=provider)
    return _runner


def reset_runner_for_tests() -> None:
    """Test-only: drop the cached singleton so the next get_runner re-creates."""
    global _runner
    _runner = None
