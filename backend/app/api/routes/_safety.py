"""Cross-route safety helpers."""
import re

from fastapi import HTTPException


_PROJECT_ID = re.compile(r"^p_[a-z0-9]{12}$")
_JOB_ID = re.compile(r"^j_[a-z0-9]{12}$")
_CHAT_ID = re.compile(r"^c_[a-z0-9]{12}$")

# Control chars (incl. NUL) we forbid in filenames. NUL would prematurely
# terminate a C-string passed to lower-level filesystem APIs, the rest are
# unprintable/garbage from a copy-paste accident.
_FILENAME_BAD_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def safe_project_id(project_id: str) -> str:
    if not _PROJECT_ID.match(project_id):
        raise HTTPException(status_code=400, detail="invalid project_id")
    return project_id


def safe_job_id(job_id: str) -> str:
    if not _JOB_ID.match(job_id):
        raise HTTPException(status_code=400, detail="invalid job_id")
    return job_id


def safe_chat_id(chat_id: str) -> str:
    if not _CHAT_ID.match(chat_id):
        raise HTTPException(status_code=400, detail="invalid chat_id")
    return chat_id


def safe_filename(name: str) -> str:
    """Validate a user-provided filename used as a path component.

    Filenames are now the only doc handle (post-d_xxx removal). The browser
    encodes the name with `encodeURIComponent` so `/` and similar can't slip
    through the path-param itself, but FastAPI's `{name:path}` converter
    accepts segments — so we still defensively reject any path separator,
    parent-traversal segment, control char, or NUL. Length is bounded at 255
    bytes (POSIX NAME_MAX). Returns the validated name unchanged."""
    if not isinstance(name, str) or not name:
        raise HTTPException(status_code=400, detail="invalid filename")
    if len(name.encode("utf-8")) > 255:
        raise HTTPException(status_code=400, detail="invalid filename")
    if "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail="invalid filename")
    if name in (".", ".."):
        raise HTTPException(status_code=400, detail="invalid filename")
    if _FILENAME_BAD_CHARS.search(name):
        raise HTTPException(status_code=400, detail="invalid filename")
    return name
