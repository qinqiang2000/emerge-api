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
- payload sniffing happens here so the agent never sees a spoofed file:
  - pdf/png/jpg use magic-byte allowlist (same as `tools.docs.upload_doc`)
  - yml/yaml/json/csv/txt/md must be valid UTF-8 and ≤256 KiB (config-shaped)
- claim is move-not-copy and removes the staging directory atomically
- abandoned staging entries are cleaned by `cleanup_stale()` on app startup
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import shutil
import time
from pathlib import Path
from typing import Literal

from app.tools.docs import upload_doc
from app.workspace.paths import (
    chat_attachments_dir,
    dedupe_filename,
    unbound_chat_attachments_dir,
)


_STAGE_TOKEN_RE = re.compile(r"^st_[a-f0-9]{16}$")

# Doc-shaped (binary) extensions go through the magic-byte gate.
_DOC_EXT = {"pdf": "pdf", "png": "png", "jpg": "jpg", "jpeg": "jpg"}

# Text-shaped extensions get the UTF-8 + size cap gate. None of these have
# stable magic bytes, so we lean on "looks textual" rather than sniffing
# specific signatures. 256 KiB is plenty for config-shaped payloads (schemas,
# notes, small csv samples); bigger means user grabbed the wrong file.
_TEXT_EXT = {"yml", "yaml", "json", "csv", "txt", "md"}
_TEXT_MAX_BYTES = 256 * 1024

_ALLOWED_EXT = {**_DOC_EXT, **{e: e for e in _TEXT_EXT}}

_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"%PDF", "pdf"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
)


AttachmentKind = Literal["doc", "schema", "data", "note"]


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


def _raw_ext(filename: str) -> str:
    """Return the lowercase filename extension (no dot). Raise StagingError if
    the filename has no extension or the extension isn't in the allowlist."""
    if "." not in filename:
        raise StagingError(f"unsupported file type: {filename!r}")
    raw = filename.rsplit(".", 1)[1].lower()
    if raw not in _ALLOWED_EXT:
        raise StagingError(f"unsupported file type: {filename!r}")
    return raw


def _filename_ext(filename: str) -> str:
    """Return the canonical normalised extension (jpeg→jpg, txt→txt, …).
    Raises StagingError on unknown extensions."""
    return _ALLOWED_EXT[_raw_ext(filename)]


def _sanitize_filename(filename: str) -> str:
    """Strip directory components; keep only the basename. Reject empty."""
    base = Path(filename).name
    if not base or base in (".", ".."):
        raise StagingError(f"invalid filename: {filename!r}")
    return base


def _validate_text_payload(safe_name: str, data: bytes) -> None:
    """Gate for text-shaped extensions (yml/yaml/json/csv/txt/md). Two-pronged:
    - cap at `_TEXT_MAX_BYTES` (these are config-shaped, not bulk data)
    - require valid UTF-8 (cheap "looks textual" check without python-magic)

    Raises StagingError on either failure."""
    if len(data) > _TEXT_MAX_BYTES:
        raise StagingError(
            f"oversize: {safe_name!r} is {len(data)} bytes, max "
            f"{_TEXT_MAX_BYTES}"
        )
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise StagingError(
            f"unsupported content: {safe_name!r} is not valid UTF-8 ({e})"
        ) from None


def _classify_kind(filename: str, data: bytes) -> AttachmentKind:
    """Classify a staged/attached file into an `AttachmentKind`. Routes the
    agent's downstream behaviour:

    | ext              | kind     |
    |------------------|----------|
    | pdf/png/jpg/jpeg | doc      |
    | yml/yaml         | schema   |
    | json             | schema if root is a list of `{name,type,...}` dicts;  |
    |                  | else `note` (best-effort)                              |
    | csv              | data     |
    | txt/md           | note     |

    Defensive fallback: unknown extensions land as `note`. The caller is
    expected to have already gone through `stage_file` / the chat-attach
    route, both of which reject unknown extensions before reaching here.
    """
    raw = filename.rsplit(".", 1)[1].lower() if "." in filename else ""
    if raw in _DOC_EXT:
        return "doc"
    if raw in {"yml", "yaml"}:
        return "schema"
    if raw == "json":
        # Heuristic: a JSON payload that looks like a schema list (top-level
        # array of `{name, type, ...}` dicts) gets `kind=schema`. Anything
        # else degrades to `note`. Parse failures also degrade — the
        # `import_schema_from_yaml` path will surface the real parser error
        # at import time, so a wrong classification here just routes the
        # agent through "ask before doing" rather than crashing.
        try:
            parsed = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return "note"
        if (
            isinstance(parsed, list)
            and parsed
            and all(
                isinstance(item, dict) and "name" in item and "type" in item
                for item in parsed
            )
        ):
            return "schema"
        return "note"
    if raw == "csv":
        return "data"
    # txt/md and any defensive fallback.
    return "note"


async def stage_file(workspace: Path, data: bytes, filename: str) -> dict[str, str | int]:
    """Persist `data` under a fresh stage_token and return a summary the
    frontend can display in the chip.

    Two-pronged sniff (per ext class):
    - pdf/png/jpg use magic-byte allowlist (same as `tools.docs.upload_doc`)
    - yml/yaml/json/csv/txt/md use UTF-8 validity + 256 KiB cap

    Counts pages opportunistically for PDFs; defaults to 1 for everything else.
    """
    safe_name = _sanitize_filename(filename)
    raw = _raw_ext(safe_name)
    if raw in _DOC_EXT:
        sniff = _sniff_ext(data)
        if sniff is None:
            raise StagingError(
                f"unsupported content: {safe_name!r} bytes don't match pdf/png/jpg"
            )
        name_ext = _DOC_EXT[raw]
        ext = sniff if sniff != name_ext else name_ext
    else:
        # Text-shaped: validate but report the user-visible filename ext rather
        # than re-sniffing (no stable magic bytes for these).
        _validate_text_payload(safe_name, data)
        ext = _ALLOWED_EXT[raw]

    token = new_stage_token()
    dirp = stage_dir(workspace, token)
    dirp.mkdir(parents=True, exist_ok=False)
    target = dirp / safe_name
    target.write_bytes(data)

    sha = hashlib.sha256(data).hexdigest()
    page_count = _count_pages(data, ext)
    kind = _classify_kind(safe_name, data)
    return {
        "stage_token": token,
        "filename": safe_name,
        "ext": ext,
        "kind": kind,
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


async def claim_staged_to_unbound_chat(
    workspace: Path,
    stage_token: str,
    chat_id: str,
) -> str:
    """Move a staged file into `_chats/<chat_id>/attachments/` with dedupe.
    Parallel of `claim_staged_to_chat` for chats that don't have a project yet.
    No sidecar — unbound-chat attachments are conversational scratch.

    Returns the post-dedupe on-disk filename. Raises `StagingClaimError` if the
    token is unknown / already claimed. Promotion (chat-attachment → project
    docs) happens later as part of `promote_chat_to_project` (the per-chat dir
    is `os.rename`-d into the new project's `chats/<chat_id>/attachments/`)."""
    dirp = stage_dir(workspace, stage_token)
    if not dirp.exists() or not dirp.is_dir():
        raise StagingClaimError(f"stage_token not found: {stage_token!r}")
    files = [p for p in dirp.iterdir() if p.is_file()]
    if not files:
        raise StagingClaimError(f"stage_token has no file: {stage_token!r}")
    src = files[0]
    target_dir = unbound_chat_attachments_dir(workspace, chat_id)
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
