import asyncio
from pathlib import Path

import pytest

from app.workspace.lock import project_lock


async def test_project_lock_acquires_and_releases(workspace: Path) -> None:
    pid = "p_test"
    (workspace / pid).mkdir()
    async with project_lock(workspace, pid):
        pass  # no error means we acquired and released


async def test_project_lock_serializes_concurrent(workspace: Path) -> None:
    pid = "p_test"
    (workspace / pid).mkdir()
    order: list[str] = []

    async def worker(name: str, hold_for: float) -> None:
        async with project_lock(workspace, pid):
            order.append(f"start:{name}")
            await asyncio.sleep(hold_for)
            order.append(f"end:{name}")

    await asyncio.gather(worker("A", 0.1), worker("B", 0.05))

    # Either A finished entirely before B started, or vice versa
    assert order in (
        ["start:A", "end:A", "start:B", "end:B"],
        ["start:B", "end:B", "start:A", "end:A"],
    )


async def test_project_lock_creates_lock_file(workspace: Path) -> None:
    pid = "p_test"
    (workspace / pid).mkdir()
    async with project_lock(workspace, pid):
        assert (workspace / pid / ".lock").exists()
