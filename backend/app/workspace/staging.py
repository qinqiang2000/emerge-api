"""Pre-project file staging.

Dropped files are uploaded the moment a user drops them into the empty-hero
state — before a project exists. Each staged file lives in
`workspace/_staging/{stage_token}/{filename}` with no pid binding. When the
user submits the turn that triggers `create_project`, `chat_turn` claims the
staged files into the freshly minted project's `docs/` directory.

Hard rules:
- staging NEVER mints a project_id (so a user retrying after a network failure
  does not litter the workspace with stale pids)
- stage_token is a 16-hex-char random opaque id, surfaced to the frontend
- magic-byte sniffing happens here (same allowlist as `tools.docs.upload_doc`)
  so the agent never sees a spoofed file
- claim is move-not-copy and removes the staging directory atomically
- abandoned staging entries are cleaned by `cleanup_stale()` on app startup
"""
from __future__ import annotations

import hashlib
import re
import secrets
import shutil
import time
from pathlib import Path

from app.tools.docs import upload_doc
from app.workspace.paths import chat_attachments_dir, dedupe_filename


_STAGE_TOKEN_RE = re.compile(r"^st_[a-f0-9]{16}$")

_ALLOWED_EXT = {"pdf": "pdf", "png": "png", "jpg": "jpg", "jpeg": "jpg"}

_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"%PDF", "pdf"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
)


class StagingError(ValueError):
    """Bad payload at stage time (unsupported type, oversize, etc.)."""


class StagingClaimError(LookupError):
    """Token unknown / already claimed / stage dir missing on claim."""


def staging_root(workspace: Path) -> Path:
    return workspace / "_staging"


def stage_dir(workspace: Path, stage_token: str) -> Path:
    if not _STAGE_TOKEN_RE.match(stage_token):
        raise StagingClaimError(f"invalid stage_token: {stage_token!r}")
    return staging_root(workspace) / stage_token


def new_stage_token() -> str:
    return f"st_{secrets.token_hex(8)}"


def _sniff_ext(data: bytes) -> str | None:
    for prefix, ext in _MAGIC:
        if data.startswith(prefix):
            return ext
    return None


def _filename_ext(filename: str) -> str:
    if "." not in filename:
        raise StagingError(f"unsupported file type: {filename!r}")
    raw = filename.rsplit(".", 1)[1].lower()
    if raw not in _ALLOWED_EXT:
        raise StagingError(f"unsupported file type: {filename!r}")
    return _ALLOWED_EXT[raw]


def _sanitize_filename(filename: str) -> str:
    """Strip directory components; keep only the basename. Reject empty."""
    base = Path(filename).name
    if not base or base in (".", ".."):
        raise StagingError(f"invalid filename: {filename!r}")
    return base


async def stage_file(workspace: Path, data: bytes, filename: str) -> dict[str, str | int]:
    """Persist `data` under a fresh stage_token and return a summary the
    frontend can display in the chip.

    Sniffs magic bytes to reject spoofed types up front (same allowlist as
    `tools.docs.upload_doc`). Counts pages opportunistically; falls back to 1
    when PyMuPDF can't open the bytes (rare; still recoverable downstream).
    """
    safe_name = _sanitize_filename(filename)
    name_ext = _filename_ext(safe_name)
    sniff = _sniff_ext(data)
    if sniff is None:
        raise StagingError(
            f"unsupported content: {safe_name!r} bytes don't match pdf/png/jpg"
        )
    ext = sniff if sniff != name_ext else name_ext

    token = new_stage_token()
    dirp = stage_dir(workspace, token)
    dirp.mkdir(parents=True, exist_ok=False)
    target = dirp / safe_name
    target.write_bytes(data)

    sha = hashlib.sha256(data).hexdigest()
    page_count = _count_pages(data, ext)
    return {
        "stage_token": token,
        "filename": safe_name,
        "ext": ext,
        "sha256": sha,
        "page_count": page_count,
        "size": len(data),
    }


def _count_pages(data: bytes, ext: str) -> int:
    if ext != "pdf":
        return 1
    try:
        import fitz

        with fitz.open(stream=data, filetype="pdf") as doc:
            return doc.page_count
    except Exception:
        return 1


async def claim_staged(
    workspace: Path,
    stage_token: str,
    project_id: str,
) -> str:
    """Move a staged file into `{project_id}/docs/` via the regular
    upload_doc pipeline. Returns the post-dedupe on-disk filename — the only
    doc handle now (no `d_xxx`). Removes the staging dir on success. Raises
    `StagingClaimError` if the token is unknown.

    The claim deliberately routes through `tools.docs.upload_doc` so the
    sidecar (`docs/.meta/<filename>.json`) and slug/dedupe invariants are
    identical to a normal `/lab/projects/{pid}/upload` — staging is just a
    timing shift, not a separate storage path.
    """
    dirp = stage_dir(workspace, stage_token)
    if not dirp.exists() or not dirp.is_dir():
        raise StagingClaimError(f"stage_token not found: {stage_token!r}")
    files = [p for p in dirp.iterdir() if p.is_file()]
    if not files:
        raise StagingClaimError(f"stage_token has no file: {stage_token!r}")
    # One file per stage dir by construction.
    src = files[0]
    data = src.read_bytes()
    filename = src.name
    meta = await upload_doc(workspace, project_id, data, filename)
    shutil.rmtree(dirp, ignore_errors=True)
    return meta["filename"]


async def claim_staged_to_chat(
    workspace: Path,
    stage_token: str,
    slug: str,
    chat_id: str,
) -> str:
    """Move a staged file into `chats/<chat_id>/attachments/` with dedupe.
    No sidecar — chat attachments are ephemeral, not curated samples.

    Returns the post-dedupe on-disk filename. Raises `StagingClaimError` if
    the token is unknown. Promotion to `docs/` is a separate, explicit step
    via the `promote_attachment_to_docs` tool — see the design note in
    `docs/superpowers/plans/2026-05-14-paste-attachments-vs-docs.md`."""
    dirp = stage_dir(workspace, stage_token)
    if not dirp.exists() or not dirp.is_dir():
        raise StagingClaimError(f"stage_token not found: {stage_token!r}")
    files = [p for p in dirp.iterdir() if p.is_file()]
    if not files:
        raise StagingClaimError(f"stage_token has no file: {stage_token!r}")
    src = files[0]
    target_dir = chat_attachments_dir(workspace, slug, chat_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    final_name = dedupe_filename(target_dir, src.name)
    target = target_dir / final_name
    shutil.move(str(src), str(target))
    shutil.rmtree(dirp, ignore_errors=True)
    return final_name


def cleanup_stale(workspace: Path, max_age_hours: float = 24.0) -> int:
    """Drop staged dirs older than `max_age_hours`. Called on app startup so
    a long-abandoned drop doesn't grow the workspace forever. Returns the
    number of stage dirs removed. Safe to call when staging root is missing.
    """
    root = staging_root(workspace)
    if not root.exists():
        return 0
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for child in root.iterdir():
        if not child.is_dir() or not _STAGE_TOKEN_RE.match(child.name):
            continue
        try:
            mtime = child.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
    return removed
