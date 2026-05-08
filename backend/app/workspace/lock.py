import asyncio
import fcntl
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from app.workspace.paths import project_dir


@asynccontextmanager
async def project_lock(workspace: Path, project_id: str) -> AsyncIterator[None]:
    """Exclusive flock on {pid}/.lock. Blocks (in a thread) until acquired."""
    pdir = project_dir(workspace, project_id)
    pdir.mkdir(parents=True, exist_ok=True)
    lock_path = pdir / ".lock"
    fd = lock_path.open("w")
    try:
        await asyncio.to_thread(fcntl.flock, fd.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
    finally:
        fd.close()
