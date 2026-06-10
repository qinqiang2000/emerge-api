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
_MAX_WRITE_BYTES = 1024 * 1024

# Red line: `schema.json` is only ever modified through the `write_schema` tool
# (atomic prompt versioning). Enforced server-side like the secret denylist.
_TYPED_ONLY_BASENAMES = frozenset({"schema.json"})


class WsPathError(ValueError):
    """A workspace path escaped the team root or hit the secret denylist."""

    def __init__(self, rel: str, reason: str) -> None:
        self.rel = rel
        self.reason = reason
        super().__init__(f"{reason}: {rel!r}")


def _safe_ws_path(workspace: Path, rel: str, write: bool = False) -> Path:
    """Resolve ``rel`` under ``workspace`` and prove it stays inside.

    ``.resolve()`` collapses ``..`` and follows symlinks, so the post-resolve
    containment check defeats both traversal and symlink-escape. The team root
    is itself resolved so a symlinked workspace still compares correctly.
    ``write=True`` additionally refuses files that only a typed tool may touch.
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
    if write and candidate.name in _TYPED_ONLY_BASENAMES:
        raise WsPathError(rel, "schema.json is only modified through write_schema")
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


# ── write side ───────────────────────────────────────────────────────────────
# Parameter names deliberately CLONE the SDK built-in Write/Edit schemas
# (file_path/content, file_path/old_string/new_string/replace_all): the model's
# trained muscle memory on the built-ins transfers, so the skill's local branch
# (built-in Write/Edit) and remote branch (ws_write/ws_edit) read identically.
# There is NO ws_delete — deletion goes through trash.py / delete_project (red
# line: never physically destroy user data).

def ws_write(workspace: Path, file_path: str, content: str) -> dict:
    """Create or overwrite a UTF-8 text file under the team workspace.

    Parents are created. Overwriting an existing *binary* file is refused —
    that would irrecoverably destroy a user doc (text overwrites are the normal
    edit cycle; docs are not). Invariant-bearing files stay typed-only:
    ``schema.json`` → ``write_schema`` (enforced in the path guard).
    """
    target = _safe_ws_path(workspace, file_path, write=True)
    if len(content.encode("utf-8")) > _MAX_WRITE_BYTES:
        return {"path": file_path, "error": f"content exceeds {_MAX_WRITE_BYTES} bytes"}
    if target.is_dir():
        return {"path": file_path, "error": "path is a directory"}
    created = not target.exists()
    if not created:
        try:
            target.read_bytes()[:4096].decode("utf-8")
        except UnicodeDecodeError:
            return {"path": file_path, "error": "refusing to overwrite a binary file (use a new path)"}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"path": file_path, "created": created, "bytes": len(content.encode("utf-8"))}


def ws_edit(
    workspace: Path, file_path: str, old_string: str, new_string: str,
    replace_all: bool = False,
) -> dict:
    """Exact-string replacement in a workspace text file (built-in Edit clone).

    Same contract as the SDK built-in: ``old_string`` must exist and — unless
    ``replace_all`` — be unique; ``old_string == new_string`` is an error.
    """
    target = _safe_ws_path(workspace, file_path, write=True)
    if not target.exists() or not target.is_file():
        return {"path": file_path, "error": "no such file"}
    if old_string == new_string:
        return {"path": file_path, "error": "old_string and new_string are identical"}
    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"path": file_path, "error": "binary file — ws_edit only edits text"}
    count = text.count(old_string)
    if count == 0:
        return {"path": file_path, "error": "old_string not found in file"}
    if count > 1 and not replace_all:
        return {"path": file_path,
                "error": f"old_string matches {count} times — add context to make it unique, "
                         "or set replace_all=true"}
    target.write_text(text.replace(old_string, new_string), encoding="utf-8")
    return {"path": file_path, "replacements": count if replace_all else 1}


def ws_move(
    workspace: Path, source_path: str, destination_path: str, copy: bool = False,
) -> dict:
    """Move (or with ``copy=True`` copy) a file/directory inside the team
    workspace — remote ``mv`` / ``cp``. Copy is how a remote client gets a
    binary doc into ``docs/`` (``ws_write`` is text-only). Refuses to clobber
    an existing destination: silent overwrite is data destruction, and
    deletion never happens through ``ws_*``.
    """
    src = _safe_ws_path(workspace, source_path, write=not copy)
    dst = _safe_ws_path(workspace, destination_path, write=True)
    if not src.exists():
        return {"src": source_path, "error": "no such source"}
    if dst.exists():
        return {"src": source_path, "dst": destination_path,
                "error": "destination already exists — refusing to overwrite"}
    if src == workspace.resolve():
        return {"src": source_path, "error": "cannot move the workspace root"}
    dst.parent.mkdir(parents=True, exist_ok=True)
    if copy:
        import shutil
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    else:
        src.rename(dst)
    return {"src": source_path, "dst": destination_path, ("copied" if copy else "moved"): True}
