"""Shared exclusive flock for every `_auth/*` mutation.

All auth mutators (users, teams, PATs) serialise on a single `_auth/.lock` so
concurrent signups / token mints can't lose-update each other. Reads stay
lock-free. Mirrors `app/workspace/lock.py::project_lock` but scoped to the
global `_auth/` dir instead of a project.
"""

from __future__ import annotations

import asyncio
import fcntl
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from app.workspace.paths import auth_dir


@asynccontextmanager
async def auth_lock(root: Path) -> AsyncIterator[None]:
    d = auth_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    fd = (d / ".lock").open("w")
    try:
        await asyncio.to_thread(fcntl.flock, fd.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
    finally:
        fd.close()
