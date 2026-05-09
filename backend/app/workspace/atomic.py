import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _atomic_replace(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    tmp = Path(tmp_str)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


def atomic_write_bytes(target: Path, data: bytes) -> None:
    _atomic_replace(target, data)


def atomic_write_text(target: Path, text: str, encoding: str = "utf-8") -> None:
    _atomic_replace(target, text.encode(encoding))


def atomic_write_json(target: Path, data: Any) -> None:
    payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False).encode("utf-8")
    _atomic_replace(target, payload)
