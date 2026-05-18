"""Workspace-aware permission gate for the Claude Agent SDK ``can_use_tool``
callback.

Replaces the prior emerge-MCP-only allowlist with a three-tier policy that
lets the agent use SDK built-ins (Bash / Read / Write / Edit / Glob / Grep /
Task* / etc.) for routine filesystem ops inside the workspace, while still
hard-blocking secret paths and asking the user for network / out-of-workspace
operations.

The classifier (`classify`) is a pure function — easy to unit-test. The
runtime gate (`workspace_safety_gate`) layers the async ask-user-and-wait
mechanism on top via a per-chat pending-permission registry.

Design notes:

- ``ask`` returns synthesised via SDK ``PermissionResultAllow`` /
  ``PermissionResultDeny`` after the user replies — the SDK callback contract
  only permits allow/deny, so emerge implements the prompt round-trip itself.
- The registry lives at module scope keyed by ``(chat_id, request_id)`` because
  ``ChatService`` is instantiated fresh per HTTP request (see
  ``chat.py:_get_chat_service``); a per-instance dict would die before the
  HTTP route can resolve the future.
- ``always`` decisions are scoped per ``chat_id`` and held in process memory
  only; persistence across restarts is out of scope for Step A.
"""
from __future__ import annotations

import asyncio
import os
import re
import shlex
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny


# ── Foreign / dangerous tools we always refuse to expose ──────────────────
# These are SDK / IDE built-ins that emerge has no business running. PowerShell
# is platform-specific and noisy; the foreign MCP namespaces are leftover from
# user-level Claude Code settings (we set ``setting_sources=[]`` so they
# shouldn't surface, but keep them in this list as defense in depth).
_FOREIGN_OR_USELESS_TOOLS = frozenset({
    "PowerShell",
})
_FOREIGN_MCP_PREFIXES = (
    "mcp__claude_ai_",
    "mcp__plugin_chrome-devtools-",
    "mcp__plugin_chrome_devtools-",
    "mcp__excalidraw__",
    "mcp__plugin_chrome-devtools",
)

_EMERGE_TOOL_PREFIX = "mcp__emerge_tools__"

# Keywords whose appearance in any tool input (Bash command, Read/Write/Edit
# path, etc.) trips a hard deny. The intent here is defense-in-depth for the
# CLAUDE.md "never print provider keys" rule.
_SECRET_LITERAL_PATTERNS = (
    re.compile(r"\bprovider_key\b", re.IGNORECASE),
    re.compile(r"\bapi[_-]?key\b", re.IGNORECASE),
    re.compile(r"\bsecret(?:_key)?\b", re.IGNORECASE),
    re.compile(r"\btoken\b", re.IGNORECASE),
)

# Hard-block path globs (anchor against absolute paths). `~/.ssh/*`,
# `.git/config`, and any `.env` filename. We match suffix-style so the rules
# bite no matter where the file lives.
_HARD_BLOCK_PATH_FRAGMENTS = (
    "/.ssh/",
    "/.aws/",
    "/.config/gcloud/",
    "/.git/config",
    "/.git/credentials",
)

# Network-touching commands inside Bash trigger an ask-user round-trip.
_NETWORK_COMMAND_TOKENS = frozenset({
    "curl", "wget", "nc", "ncat", "ssh", "scp", "rsync", "ftp", "telnet",
})

# Tools we treat as "filesystem ops" — the input usually carries a path we can
# range-check against the workspace. ``Glob``/``Grep`` accept either a pattern
# or a directory; we cover both shapes.
_FS_TOOLS = frozenset({
    "Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "Glob", "Grep",
})


Behavior = Literal["allow", "deny", "ask"]


@dataclass(frozen=True)
class GateDecision:
    """Triage outcome for a single tool invocation.

    ``behavior``: what the gate concluded.
    ``reason``: short human-readable explanation; surfaced in the
        SSE ``permission_request`` payload (ask) or the deny ``message``.
    """
    behavior: Behavior
    reason: str


def _is_secret_literal(text: str) -> bool:
    if not text:
        return False
    return any(p.search(text) for p in _SECRET_LITERAL_PATTERNS)


def _is_hard_block_path(absolute_path: str) -> bool:
    """Return True when ``absolute_path`` points at a known-sensitive file."""
    p = absolute_path.lower()
    if any(frag in p for frag in _HARD_BLOCK_PATH_FRAGMENTS):
        return True
    # Bare `.env` (or `.env.<anything>`) at any level.
    name = os.path.basename(absolute_path)
    if name == ".env" or name.startswith(".env."):
        return True
    return False


def _resolve_path(raw: str, *, cwd: Path) -> Path:
    """Resolve ``raw`` against ``cwd`` without following symlinks (we want the
    pre-symlink string to bite, so an attacker can't deref away from a sensitive
    path). Falls back to a plain join for paths we can't normalise."""
    try:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = cwd / candidate
        # ``os.path.normpath`` collapses ``..`` without touching the FS.
        return Path(os.path.normpath(str(candidate)))
    except (TypeError, ValueError):
        return cwd


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except (ValueError, OSError):
        # Fall back to string-prefix check — covers the common case where
        # neither side exists yet (fresh Write target).
        try:
            return str(path).startswith(str(root) + os.sep) or str(path) == str(root)
        except (TypeError, ValueError):
            return False


def _extract_bash_paths(command: str) -> list[str]:
    """Pull out plausible path-shaped tokens from a Bash command line.

    Heuristic, not a full shell parser. We tokenize with ``shlex`` (which
    handles quotes), then keep tokens that look like paths (contain ``/`` or
    start with ``.``/``~``). This is enough to spot ``cat /tmp/secret`` or
    ``rm -rf ~/.ssh/id_rsa``.
    """
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        # Unbalanced quotes — fall back to whitespace split.
        tokens = command.split()
    paths: list[str] = []
    for tok in tokens:
        if not tok:
            continue
        if tok.startswith("-"):
            continue
        if "/" in tok or tok.startswith("~") or tok.startswith("."):
            paths.append(tok)
    return paths


def _bash_uses_network(command: str) -> bool:
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()
    return any(t in _NETWORK_COMMAND_TOKENS for t in tokens)


def classify(
    tool_name: str,
    tool_input: dict[str, Any],
    *,
    workspace_root: Path,
) -> GateDecision:
    """Decide allow / deny / ask for a single tool call.

    The signature is deliberately framework-free so unit tests can drive
    every branch with literal dicts.
    """
    name = tool_name or ""

    # 1. Hard deny: foreign / useless tools.
    if name in _FOREIGN_OR_USELESS_TOOLS:
        return GateDecision("deny", f"Tool '{name}' is not enabled in emerge.")
    if any(name.startswith(p) for p in _FOREIGN_MCP_PREFIXES):
        return GateDecision(
            "deny",
            f"Foreign MCP tool '{name}' is not enabled in emerge.",
        )

    # 2. emerge's own MCP tools — always allow. These are the business
    # tools we ship; access control is enforced inside each tool body, not
    # at the SDK gate.
    if name.startswith(_EMERGE_TOOL_PREFIX):
        return GateDecision("allow", "emerge MCP tool")

    workspace_root = workspace_root.resolve()

    # 3. Bash — special-cased because the input is an opaque string.
    if name in ("Bash", "BashOutput", "KillBash"):
        command = str(tool_input.get("command") or "")
        cwd_raw = str(tool_input.get("cwd") or "")
        cwd = Path(cwd_raw) if cwd_raw else workspace_root

        if _is_secret_literal(command):
            return GateDecision(
                "deny",
                "Command contains a secret-looking literal (api_key / secret / token).",
            )

        # Network ops always ask — even if cwd is workspace-internal.
        if _bash_uses_network(command):
            return GateDecision(
                "ask",
                "Command performs a network operation (curl/wget/ssh/...).",
            )

        # Inspect path-shaped tokens.
        for raw in _extract_bash_paths(command):
            resolved = _resolve_path(raw, cwd=cwd)
            if _is_hard_block_path(str(resolved)):
                return GateDecision(
                    "deny",
                    f"Path '{raw}' targets a sensitive location.",
                )
            if not _within(resolved, workspace_root):
                if _within(resolved, workspace_root.parent):
                    return GateDecision(
                        "deny",
                        f"Command touches application source code outside the workspace ({raw}).",
                    )
                return GateDecision(
                    "ask",
                    f"Command touches a path outside the workspace ({raw}).",
                )

        # cwd outside workspace also asks.
        if cwd_raw and not _within(cwd, workspace_root):
            return GateDecision(
                "ask",
                f"Command cwd '{cwd_raw}' is outside the workspace.",
            )

        return GateDecision("allow", "Bash inside workspace")

    # 4. Filesystem tools — check the (possibly nested) path field.
    if name in _FS_TOOLS:
        # Path lives under one of these keys depending on the tool.
        path_str = (
            tool_input.get("file_path")
            or tool_input.get("path")
            or tool_input.get("notebook_path")
            or ""
        )
        # Glob/Grep accept "pattern" + optional "path"; the path field is what
        # we range-check, and the pattern itself is informative only.
        if not path_str and name in ("Glob", "Grep"):
            path_str = tool_input.get("path") or ""

        if not path_str:
            # No path means "search cwd"; treat as workspace-internal (allow).
            # The SDK never executes outside its spawned cwd in our setup.
            return GateDecision("allow", f"{name} with no explicit path")

        resolved = _resolve_path(str(path_str), cwd=workspace_root)
        if _is_hard_block_path(str(resolved)):
            return GateDecision(
                "deny",
                f"Path '{path_str}' targets a sensitive location.",
            )
        if _is_secret_literal(str(path_str)):
            return GateDecision(
                "deny",
                f"Path '{path_str}' contains a secret-looking literal.",
            )
        if not _within(resolved, workspace_root):
            # Deny reads of application source code (inside the project root
            # but outside the workspace). Tool descriptions are the agent's
            # contract; it should never need to read the implementation.
            if _within(resolved, workspace_root.parent):
                return GateDecision(
                    "deny",
                    f"{name} targets application source code outside the workspace.",
                )
            # Reads of other out-of-workspace paths (e.g. ~/Downloads, Desktop)
            # ask the user; we let them opt in.
            return GateDecision(
                "ask",
                f"{name} touches a path outside the workspace ({path_str}).",
            )
        return GateDecision("allow", f"{name} inside workspace")

    # 5. Network-fetch tools — always ask.
    if name in ("WebFetch", "WebSearch"):
        url = tool_input.get("url") or tool_input.get("query") or ""
        return GateDecision("ask", f"{name} → {url}")

    # 6. Task orchestration / TodoWrite / Monitor / Cron* — allow. These are
    # pure agent-side bookkeeping and don't touch the host.
    if name in (
        "Task", "TaskCreate", "TaskUpdate", "TaskList", "TaskStop",
        "TodoWrite", "ExitPlanMode", "Monitor",
    ) or name.startswith("Cron"):
        return GateDecision("allow", f"{name} (agent bookkeeping)")

    # 7. Default — ask. Better to surface unknown tools to the human than to
    # silently allow.
    return GateDecision("ask", f"Unrecognised tool '{name}'.")


# ── Async ask-user round-trip ─────────────────────────────────────────────

# Module-level registry. Keys are ``(chat_id, request_id)``; values are the
# futures the can_use_tool callback awaits. The HTTP route resolves the
# future via ``resolve_permission`` when the user clicks Approve / Deny.
_pending: dict[tuple[str, str], asyncio.Future[dict[str, Any]]] = {}
_pending_lock = asyncio.Lock()

# Per-chat "always allow" patterns. Set of ``tool_name`` strings for now —
# Step A doesn't try to be clever about scoping by input pattern. Cleared
# when the process restarts (explicitly NOT persisted to disk).
_always_allow: dict[str, set[str]] = {}


def is_always_allowed(chat_id: str, tool_name: str) -> bool:
    return tool_name in _always_allow.get(chat_id, set())


def mark_always_allow(chat_id: str, tool_name: str) -> None:
    _always_allow.setdefault(chat_id, set()).add(tool_name)


async def request_permission(
    *,
    chat_id: str,
    tool_name: str,
    tool_input: dict[str, Any],
    reason: str,
    sse_writer,  # SSEWriter | None — typed loosely to avoid circular import.
) -> PermissionResultAllow | PermissionResultDeny:
    """Emit a ``permission_request`` SSE event and block until the user
    responds via ``resolve_permission``.

    If no ``sse_writer`` is bound (e.g. when called outside a chat turn),
    fall back to deny — the agent cannot wait on a UI that isn't watching.
    """
    request_id = uuid.uuid4().hex[:12]
    loop = asyncio.get_event_loop()
    future: asyncio.Future[dict[str, Any]] = loop.create_future()
    async with _pending_lock:
        _pending[(chat_id, request_id)] = future

    payload: dict[str, Any] = {
        "request_id": request_id,
        "tool_name": tool_name,
        "tool_input": tool_input,
        "reason": reason,
        "suggested_scope": "once",
    }

    if sse_writer is None:
        async with _pending_lock:
            _pending.pop((chat_id, request_id), None)
        return PermissionResultDeny(
            message=(
                f"Tool '{tool_name}' needs user approval but no UI is "
                "attached to this session."
            ),
            interrupt=False,
        )

    await sse_writer("permission_request", payload)

    try:
        decision = await future
    finally:
        async with _pending_lock:
            _pending.pop((chat_id, request_id), None)

    if decision.get("decision") == "approve":
        if decision.get("scope") == "always":
            mark_always_allow(chat_id, tool_name)
        return PermissionResultAllow()
    return PermissionResultDeny(
        message=decision.get("message") or "User denied the request.",
        interrupt=False,
    )


async def resolve_permission(
    *,
    chat_id: str,
    request_id: str,
    decision: str,
    scope: str = "once",
    message: str | None = None,
) -> bool:
    """Called by the HTTP route when the user clicks Approve / Deny.

    Returns False if the request_id is unknown or already resolved (idempotent
    no-op so a double-click can't crash the route).
    """
    async with _pending_lock:
        future = _pending.get((chat_id, request_id))
    if future is None or future.done():
        return False
    future.set_result({"decision": decision, "scope": scope, "message": message})
    return True


async def cancel_pending(chat_id: str) -> None:
    """Drop every outstanding request for a chat — used when the chat turn
    ends (success or failure) so dangling futures don't linger forever."""
    async with _pending_lock:
        stale = [k for k in _pending if k[0] == chat_id]
        for key in stale:
            fut = _pending.pop(key, None)
            if fut and not fut.done():
                fut.set_result({"decision": "deny", "message": "Chat turn ended."})


def make_gate(workspace_root: Path, *, chat_id: str, sse_writer_getter):
    """Build the async callback bound to one chat turn.

    ``sse_writer_getter`` is a zero-arg callable so we can defer the lookup
    until the callback fires (the writer ContextVar is set after the gate is
    constructed in ``ChatService._build_options``).
    """

    async def _gate(
        tool_name: str,
        tool_input: dict[str, Any],
        _ctx,
    ) -> PermissionResultAllow | PermissionResultDeny:
        # Honour any earlier "always allow" the user toggled this chat.
        if is_always_allowed(chat_id, tool_name):
            return PermissionResultAllow()
        decision = classify(tool_name, tool_input, workspace_root=workspace_root)
        if decision.behavior == "allow":
            return PermissionResultAllow()
        if decision.behavior == "deny":
            return PermissionResultDeny(message=decision.reason, interrupt=False)
        # ask
        return await request_permission(
            chat_id=chat_id,
            tool_name=tool_name,
            tool_input=tool_input,
            reason=decision.reason,
            sse_writer=sse_writer_getter(),
        )

    return _gate
