"""Personal Access Tokens — the headless `Authorization: Bearer` credential.

This is the "同事精神" half of auth: a single long-lived PAT lets Claude Code /
Claude Desktop cowork / curl drive the same `/lab/*` surface the browser uses
(see `MEMORY:priorities-efficiency-experience-over-security`). PATs are
high-entropy random strings, so we store a plain **sha256** (O(1) lookup, no
slow KDF needed — unlike passwords) in `_auth/pats.json`, mirroring the prod
`_keys.json` keystore but bound to a *user* rather than a project.

PATs never expire — only an explicit `revoke_pat` kills one. The plaintext is
shown exactly once at mint time (reveal-once, like `issue_api_key`).
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path

from app.auth.lock import auth_lock
from app.auth.store import _iso_now, _read_rows
from app.security.keys import sha256_key
from app.workspace.atomic import atomic_write_json
from app.workspace.ids import new_pat_id
from app.workspace.paths import pats_path

PAT_PREFIX = "emrg_pat_"
_PAT_BYTES = 24


def generate_pat() -> str:
    return PAT_PREFIX + secrets.token_urlsafe(_PAT_BYTES)


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


async def mint_pat(root: Path, user_id: str, label: str = "") -> tuple[str, str]:
    """Mint a PAT for `user_id`. Returns `(plaintext, pat_id)`; the plaintext is
    the only time the secret is ever available — we store sha256 only."""
    plaintext = generate_pat()
    pat_id = new_pat_id()
    async with auth_lock(root):
        rows = _read_rows(pats_path(root))
        rows.append({
            "pat_id": pat_id,
            "hash": sha256_key(plaintext),
            "user_id": user_id,
            "label": label.strip(),
            "created_at": _iso_now(),
            "last_used": None,
        })
        atomic_write_json(pats_path(root), rows)
    return plaintext, pat_id


async def verify_pat(root: Path, plaintext: str) -> str | None:
    """Resolve a bearer token to its `user_id`, or None. Lock-free read on the
    hot path; bumps `last_used` at most once per UTC day per token (bounded
    writes — efficiency over precise audit)."""
    if not plaintext or not plaintext.startswith(PAT_PREFIX):
        return None
    h = sha256_key(plaintext)
    for r in _read_rows(pats_path(root)):
        if r.get("hash") == h:
            await _touch_last_used(root, r["pat_id"])
            return r.get("user_id")
    return None


async def list_pats(root: Path, user_id: str) -> list[dict]:
    """PATs for a user, safe to serialise — no `hash`, never any plaintext."""
    return [
        {
            "pat_id": r.get("pat_id"),
            "label": r.get("label", ""),
            "created_at": r.get("created_at"),
            "last_used": r.get("last_used"),
        }
        for r in _read_rows(pats_path(root))
        if r.get("user_id") == user_id
    ]


async def revoke_pat(root: Path, pat_id: str, user_id: str) -> bool:
    """Delete a PAT. Scoped to `user_id` so one user can't revoke another's.
    Returns True if a row was removed."""
    async with auth_lock(root):
        rows = _read_rows(pats_path(root))
        kept = [
            r for r in rows
            if not (r.get("pat_id") == pat_id and r.get("user_id") == user_id)
        ]
        if len(kept) == len(rows):
            return False
        atomic_write_json(pats_path(root), kept)
    return True


async def _touch_last_used(root: Path, pat_id: str) -> None:
    today = _today()
    # cheap pre-check (lock-free): skip if already stamped today
    for r in _read_rows(pats_path(root)):
        if r.get("pat_id") == pat_id:
            if (r.get("last_used") or "")[:10] == today:
                return
            break
    else:
        return
    async with auth_lock(root):
        rows = _read_rows(pats_path(root))
        changed = False
        for r in rows:
            if r.get("pat_id") == pat_id and (r.get("last_used") or "")[:10] != today:
                r["last_used"] = _iso_now()
                changed = True
                break
        if changed:
            atomic_write_json(pats_path(root), rows)
