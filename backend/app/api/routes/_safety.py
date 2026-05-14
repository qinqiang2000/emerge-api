"""Cross-route safety helpers."""
import re

from fastapi import HTTPException


_PROJECT_ID = re.compile(r"^p_[a-z0-9]{12}$")
_JOB_ID = re.compile(r"^j_[a-z0-9]{12}$")
_CHAT_ID = re.compile(r"^c_[a-z0-9]{12}$")
_PUBLISHED_ID = re.compile(r"^pub_[a-z0-9]{12}$")

# Control chars (incl. NUL) we forbid in filenames. NUL would prematurely
# terminate a C-string passed to lower-level filesystem APIs, the rest are
# unprintable/garbage from a copy-paste accident.
_FILENAME_BAD_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def safe_project_id(project_id: str) -> str:
    if not _PROJECT_ID.match(project_id):
        raise HTTPException(status_code=400, detail="invalid project_id")
    return project_id


def safe_slug(slug: str) -> str:
    """Validate a project slug used as folder name + path segment.

    Slugs are human-readable handles — `us-invoice`, `美国发票`, `q4-美国发票`.
    Unicode is allowed (CJK, emoji, …), but the value must be a safe filesystem
    component and a safe URL segment: 1–64 *characters* long, no slash /
    backslash, no NUL or other control chars, not `.` or `..`. Length is
    measured in characters (not bytes) because that's what UI users will
    perceive."""
    if not isinstance(slug, str):
        raise HTTPException(status_code=400, detail="invalid slug")
    n = len(slug)
    if n < 1 or n > 64:
        raise HTTPException(status_code=400, detail="invalid slug")
    if "/" in slug or "\\" in slug:
        raise HTTPException(status_code=400, detail="invalid slug")
    if slug in (".", ".."):
        raise HTTPException(status_code=400, detail="invalid slug")
    if _FILENAME_BAD_CHARS.search(slug):
        raise HTTPException(status_code=400, detail="invalid slug")
    return slug


def safe_published_id(s: str) -> str:
    if not _PUBLISHED_ID.match(s or ""):
        raise HTTPException(status_code=400, detail="invalid published_id")
    return s


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
