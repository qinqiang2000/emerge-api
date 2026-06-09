"""Filesystem-over-MCP — re-expose the "workspace is the bus" model remotely.

emerge's whole agent model is *paths are the API* (see ``emerge_extractor.md``
§"Workspace is your filesystem"): the in-session agent shares the workspace
filesystem and operates it with built-in Bash/Glob/Grep/Read/Write/Edit. That
collapses for a REMOTE MCP client (Cowork/Desktop), whose Bash runs in its own
cloud sandbox and cannot see this server's disk — so the entire class of
"discover / read" capabilities goes dark (dogfood 2026-06-09: agent flailed for
9 turns trying to register a model because it could neither list models/ nor
read project.json over MCP).

These functions re-expose the team workspace as a small, generic filesystem
surface (``ws_list`` / ``ws_read`` / ``ws_grep`` …), scoped to the caller's team
root. One move restores every core object's read CRUD, because emerge's core
objects ARE files (``project.json``, ``models/{id}.json``, ``prompts/{id}.json``,
``predictions/*.json``). See plan ``2026-06-09-filesystem-over-mcp.md``.

**Containment is the security boundary AND a free secret guard.** Every path is
resolved and asserted to live under the team workspace root. Because every secret
lives at the TRUE root (``_auth`` / ``_keys.json`` / ``_published``) or the
backend root (``.env``) — all *outside* the per-team workspace — containment
alone blocks them. We keep an explicit denylist on top as defense-in-depth
(INSIGHTS #1: the ``.env`` leak must be enforced server-side, never trusted to a
prompt). These are pure functions so they get an HTTP twin + are unit-testable;
the ``@tool`` wrappers live in ``app/tools/__init__.py``.
"""
from __future__ import annotations

import re
from pathlib import Path

# Hidden by default in listings: dotfiles + leading-underscore sentinel dirs
# (`_trash`, `_chats`, `_draft`, … — same convention project scanners skip, and
# the orphan-sweep exemption relies on; see INSIGHTS teams/ incident).
_HIDDEN_PREFIXES = (".", "_")

# Defense-in-depth denylist (containment already blocks true-root secrets; this
# catches anything secret-shaped that could ever land inside a team dir).
_SECRET_RE = re.compile(r"(^|/)(\.env|.*\.key|.*\.pem|.*secret.*|_keys.*|_auth.*)$", re.IGNORECASE)

# Bounded outputs (best-practice: never load everything into context).
_MAX_READ_BYTES = 64 * 1024
_MAX_LIST_ENTRIES = 500
_MAX_GREP_HITS = 200


class WsPathError(ValueError):
    """A workspace path escaped the team root or hit the secret denylist."""

    def __init__(self, rel: str, reason: str) -> None:
        self.rel = rel
        self.reason = reason
        super().__init__(f"{reason}: {rel!r}")


def _safe_ws_path(workspace: Path, rel: str) -> Path:
    """Resolve ``rel`` under ``workspace`` and prove it stays inside.

    ``.resolve()`` collapses ``..`` and follows symlinks, so the post-resolve
    containment check defeats both traversal and symlink-escape. The team root
    is itself resolved so a symlinked workspace still compares correctly.
    """
    if not isinstance(rel, str):
        raise WsPathError(str(rel), "path must be a string")
    rel = rel.strip()
    if rel in ("", "."):
        return workspace.resolve()
    if "\x00" in rel:
        raise WsPathError(rel, "path contains NUL")
    root = workspace.resolve()
    candidate = (root / rel).resolve()
    if not candidate.is_relative_to(root):
        raise WsPathError(rel, "path escapes the team workspace")
    # Check every segment of the *relative* path against the secret denylist.
    relpath = candidate.relative_to(root).as_posix()
    if _SECRET_RE.search(relpath) or _SECRET_RE.search("/" + relpath):
        raise WsPathError(rel, "path is blocked (secret)")
    return candidate


def _hidden(name: str) -> bool:
    return name.startswith(_HIDDEN_PREFIXES)


def ws_list(workspace: Path, path: str = ".", recursive: bool = False) -> dict:
    """List a directory under the team workspace.

    Returns ``{path, entries:[{name, type, size}]}`` (shallow) or, when
    ``recursive``, a ``tree`` of nested dicts. Hidden (dot / underscore) entries
    are skipped — they're sentinels, not user content. Output is capped.
    """
    target = _safe_ws_path(workspace, path)
    if not target.exists():
        return {"path": path, "error": "no such path"}
    if target.is_file():
        st = target.stat()
        return {"path": path, "entries": [{"name": target.name, "type": "file", "size": st.st_size}]}

    if recursive:
        return {"path": path, "tree": _tree(target, budget=[_MAX_LIST_ENTRIES])}

    entries: list[dict] = []
    for child in sorted(target.iterdir(), key=lambda p: p.name):
        if _hidden(child.name):
            continue
        is_dir = child.is_dir()
        entries.append({
            "name": child.name,
            "type": "dir" if is_dir else "file",
            "size": None if is_dir else child.stat().st_size,
        })
        if len(entries) >= _MAX_LIST_ENTRIES:
            entries.append({"name": "…", "type": "truncated", "size": None})
            break
    return {"path": path, "entries": entries}


def _tree(d: Path, budget: list[int]) -> dict:
    node: dict = {}
    for child in sorted(d.iterdir(), key=lambda p: p.name):
        if _hidden(child.name) or budget[0] <= 0:
            continue
        budget[0] -= 1
        node[child.name] = _tree(child, budget) if child.is_dir() else None
    return node


def ws_read(workspace: Path, path: str, max_bytes: int = _MAX_READ_BYTES) -> dict:
    """Read a UTF-8 text/JSON file under the team workspace.

    Binary docs (PDF/image) are refused with a pointer to ``read_doc_image`` —
    doc vision is *pulled* through that tool, never base64'd through here (red
    line). Output is truncated at ``max_bytes``.
    """
    target = _safe_ws_path(workspace, path)
    if not target.exists() or not target.is_file():
        return {"path": path, "error": "no such file"}
    raw = target.read_bytes()[: max(0, max_bytes)]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return {
            "path": path,
            "error": "binary file — use read_doc_image / pdf_render_page for PDFs and images",
        }
    truncated = target.stat().st_size > len(raw)
    return {"path": path, "content": text, "truncated": truncated}


def ws_grep(workspace: Path, pattern: str, path: str = ".", glob: str | None = None) -> dict:
    """Recursive content search (the ``Grep``/``Glob`` replacement).

    Walks text files under ``path`` (optionally name-filtered by ``glob``),
    returns ``{matches:[{file, line, text}]}`` capped at a sane limit. Hidden
    sentinels and binary files are skipped.
    """
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        return {"pattern": pattern, "error": f"bad regex: {exc}"}
    base = _safe_ws_path(workspace, path)
    if not base.exists():
        return {"pattern": pattern, "error": "no such path"}
    root = workspace.resolve()
    matches: list[dict] = []
    files = [base] if base.is_file() else sorted(base.rglob(glob or "*"))
    for f in files:
        if len(matches) >= _MAX_GREP_HITS:
            break
        if not f.is_file() or any(_hidden(part) for part in f.relative_to(root).parts):
            continue
        try:
            text = f.read_bytes()[:_MAX_READ_BYTES].decode("utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if rx.search(line):
                matches.append({"file": f.relative_to(root).as_posix(), "line": i, "text": line[:300]})
                if len(matches) >= _MAX_GREP_HITS:
                    break
    return {"pattern": pattern, "matches": matches}
