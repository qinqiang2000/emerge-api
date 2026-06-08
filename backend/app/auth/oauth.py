"""OAuth 2.0 Authorization Server — emerge as a *login-based* custom connector.

P2 of plan ``2026-06-08-cowork-remote-mcp.md``. Lets a Claude client (Cowork /
Desktop / claude.ai / mobile) onboard a teammate by **logging into emerge**
instead of pasting a PAT into the connector URL — the P1 ``?token=`` path stays
as a dev/curl fallback.

The protocol heavy-lifting — ``/authorize`` ``/token`` ``/register`` (DCR)
``/revoke`` + ``.well-known`` metadata, PKCE verification, client auth — is the
``mcp.server.auth`` scaffolding (plan tip 3). This module supplies only the
emerge-specific glue: an ``OAuthAuthorizationServerProvider`` backed by the same
``_auth/*.json`` flat-file store as users/teams/PATs, with ``subject = user.id``
on every issued token so the ``/mcp`` transport resolves the caller to their
team workspace exactly like a PAT does (see ``api/mcp_remote.py``).

All state is GLOBAL (cross-team), at the TRUE workspace root ``_auth/``:

  - ``oauth_clients.json``  DCR-registered clients (persistent)
  - ``oauth_txns.json``     pending ``/authorize`` transactions → consent (TTL)
  - ``oauth_codes.json``    issued authorization codes (one-time, TTL)
  - ``oauth_tokens.json``   issued access + refresh tokens (sha256 only)

Token secrets are stored as sha256 (O(1) lookup, no plaintext at rest), mirroring
``tokens.py``. Access tokens are prefixed ``emrg_at_`` and refresh ``emrg_rt_`` so
the ``/mcp`` bearer channel tells them apart from a ``emrg_pat_`` PAT. Mutations
read-modify-write under the shared ``auth_lock``; reads are lock-free (tiny N,
last-writer-wins — same posture as ``store.py``).
"""
from __future__ import annotations

import secrets
import time
from pathlib import Path

from pydantic import AnyUrl

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from app.auth.lock import auth_lock
from app.auth.store import _read_rows
from app.config import get_settings
from app.security.keys import sha256_key
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    oauth_clients_path,
    oauth_codes_path,
    oauth_tokens_path,
    oauth_txns_path,
)

ACCESS_PREFIX = "emrg_at_"
REFRESH_PREFIX = "emrg_rt_"
CODE_PREFIX = "emrg_code_"
TXN_PREFIX = "emrg_txn_"

ACCESS_TTL = 3600          # 1h access token (clients refresh transparently)
TXN_TTL = 600             # 10min to complete consent
CODE_TTL = 300            # 5min one-time authorization code
# Refresh tokens never expire (revocable) — same "long-lived, explicit revoke"
# posture as PATs; a teammate shouldn't be forced to re-login periodically.


def oauth_enabled() -> bool:
    """OAuth AS is mounted only when a public origin is configured (it is the
    advertised issuer). Empty → teammates onboard via the P1 ``?token=`` PAT URL."""
    return bool(get_settings().public_base_url.strip())


def _now() -> int:
    return int(time.time())


def _expired(row: dict) -> bool:
    exp = row.get("expires_at")
    return exp is not None and exp < _now()


class EmergeOAuthProvider:
    """``OAuthAuthorizationServerProvider`` over emerge's flat-file ``_auth/``.

    Stateless: the workspace root is read live from settings on every call (like
    ``deps.py`` / ``store.py``), so the same singleton serves tests that chdir
    per-case and a long-running prod process identically.
    """

    def _root(self) -> Path:
        return get_settings().workspace_root

    def _base(self) -> str:
        return get_settings().public_base_url.rstrip("/")

    # --- clients (DCR) ------------------------------------------------------
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        for r in _read_rows(oauth_clients_path(self._root())):
            if r.get("client_id") == client_id:
                return OAuthClientInformationFull(**r)
        return None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        root = self._root()
        async with auth_lock(root):
            rows = [
                r for r in _read_rows(oauth_clients_path(root))
                if r.get("client_id") != client_info.client_id
            ]
            rows.append(client_info.model_dump(mode="json"))
            atomic_write_json(oauth_clients_path(root), rows)

    # --- authorize → consent handoff ---------------------------------------
    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        """Stash the request as a pending transaction and hand the browser to
        emerge's own session-gated consent screen, which (after login) mints the
        code and redirects back to the client's ``redirect_uri``."""
        txn_id = TXN_PREFIX + secrets.token_urlsafe(24)
        root = self._root()
        async with auth_lock(root):
            rows = [t for t in _read_rows(oauth_txns_path(root)) if not _expired(t)]
            rows.append({
                "txn_id": txn_id,
                "client_id": client.client_id,
                "redirect_uri": str(params.redirect_uri),
                "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
                "code_challenge": params.code_challenge,
                "scopes": params.scopes or [],
                "state": params.state,
                "resource": params.resource,
                "expires_at": _now() + TXN_TTL,
            })
            atomic_write_json(oauth_txns_path(root), rows)
        return f"{self._base()}/oauth/consent?txn={txn_id}"

    async def load_txn(self, txn_id: str) -> dict | None:
        """Used by the consent route to render the screen. None if expired/unknown."""
        for t in _read_rows(oauth_txns_path(self._root())):
            if t.get("txn_id") == txn_id and not _expired(t):
                return t
        return None

    async def _pop_txn(self, root: Path, txn_id: str) -> dict | None:
        async with auth_lock(root):
            rows = _read_rows(oauth_txns_path(root))
            txn = next((t for t in rows if t.get("txn_id") == txn_id), None)
            if txn is None or _expired(txn):
                return None
            atomic_write_json(oauth_txns_path(root), [t for t in rows if t.get("txn_id") != txn_id])
            return txn

    async def complete_authorization(self, txn_id: str, subject: str) -> str | None:
        """Consent approved by ``subject`` (an emerge user id): mint a one-time
        code bound to the PKCE challenge + subject, return the client redirect."""
        root = self._root()
        txn = await self._pop_txn(root, txn_id)
        if txn is None:
            return None
        code = CODE_PREFIX + secrets.token_urlsafe(32)
        async with auth_lock(root):
            rows = [c for c in _read_rows(oauth_codes_path(root)) if not _expired(c)]
            rows.append({
                "code_hash": sha256_key(code),
                "client_id": txn["client_id"],
                "redirect_uri": txn["redirect_uri"],
                "redirect_uri_provided_explicitly": txn["redirect_uri_provided_explicitly"],
                "code_challenge": txn["code_challenge"],
                "scopes": txn.get("scopes", []),
                "resource": txn.get("resource"),
                "subject": subject,
                "expires_at": _now() + CODE_TTL,
            })
            atomic_write_json(oauth_codes_path(root), rows)
        return construct_redirect_uri(txn["redirect_uri"], code=code, state=txn.get("state"))

    async def deny_authorization(self, txn_id: str) -> str | None:
        """Consent denied: drop the txn, bounce back with ``error=access_denied``."""
        root = self._root()
        txn = await self._pop_txn(root, txn_id)
        if txn is None:
            return None
        return construct_redirect_uri(
            txn["redirect_uri"], error="access_denied", state=txn.get("state")
        )

    # --- authorization code → token ----------------------------------------
    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        h = sha256_key(authorization_code)
        for c in _read_rows(oauth_codes_path(self._root())):
            if c.get("code_hash") == h and c.get("client_id") == client.client_id and not _expired(c):
                return AuthorizationCode(
                    code=authorization_code,
                    scopes=c.get("scopes", []),
                    expires_at=float(c["expires_at"]),
                    client_id=c["client_id"],
                    code_challenge=c["code_challenge"],
                    redirect_uri=AnyUrl(c["redirect_uri"]),
                    redirect_uri_provided_explicitly=c["redirect_uri_provided_explicitly"],
                    resource=c.get("resource"),
                    subject=c.get("subject"),
                )
        return None

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        # PKCE + redirect_uri already verified by the SDK TokenHandler. Burn the
        # code (one-time) then issue the token pair bound to the code's subject.
        root = self._root()
        h = sha256_key(authorization_code.code)
        async with auth_lock(root):
            rows = [c for c in _read_rows(oauth_codes_path(root)) if c.get("code_hash") != h]
            atomic_write_json(oauth_codes_path(root), rows)
        return await self._issue_tokens(
            client.client_id, list(authorization_code.scopes), authorization_code.subject
        )

    # --- refresh ------------------------------------------------------------
    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        if not refresh_token.startswith(REFRESH_PREFIX):
            return None
        h = sha256_key(refresh_token)
        for t in _read_rows(oauth_tokens_path(self._root())):
            if t.get("kind") == "refresh" and t.get("hash") == h and t.get("client_id") == client.client_id:
                return RefreshToken(
                    token=refresh_token,
                    client_id=t["client_id"],
                    scopes=t.get("scopes", []),
                    subject=t.get("subject"),
                    expires_at=t.get("expires_at"),
                )
        return None

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        # Rotate both tokens: drop the whole grant, mint a fresh pair.
        root = self._root()
        h = sha256_key(refresh_token.token)
        async with auth_lock(root):
            rows = _read_rows(oauth_tokens_path(root))
            grant = next((t.get("grant_id") for t in rows if t.get("hash") == h), None)
            atomic_write_json(
                oauth_tokens_path(root), [t for t in rows if t.get("grant_id") != grant]
            )
        new_scopes = scopes or list(refresh_token.scopes)
        return await self._issue_tokens(client.client_id, new_scopes, refresh_token.subject)

    # --- access token verification (used by /mcp + /token introspection) ----
    async def load_access_token(self, token: str) -> AccessToken | None:
        if not token.startswith(ACCESS_PREFIX):
            return None
        h = sha256_key(token)
        for t in _read_rows(oauth_tokens_path(self._root())):
            if t.get("kind") == "access" and t.get("hash") == h:
                if _expired(t):
                    return None
                return AccessToken(
                    token=token,
                    client_id=t["client_id"],
                    scopes=t.get("scopes", []),
                    expires_at=t.get("expires_at"),
                    subject=t.get("subject"),
                )
        return None

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        root = self._root()
        h = sha256_key(token.token)
        async with auth_lock(root):
            rows = _read_rows(oauth_tokens_path(root))
            grant = next((t.get("grant_id") for t in rows if t.get("hash") == h), None)
            if grant is None:
                return
            atomic_write_json(
                oauth_tokens_path(root), [t for t in rows if t.get("grant_id") != grant]
            )

    # --- internal -----------------------------------------------------------
    async def _issue_tokens(self, client_id: str, scopes: list[str], subject: str | None) -> OAuthToken:
        grant_id = secrets.token_urlsafe(12)
        access = ACCESS_PREFIX + secrets.token_urlsafe(32)
        refresh = REFRESH_PREFIX + secrets.token_urlsafe(32)
        now = _now()
        root = self._root()
        async with auth_lock(root):
            # Prune expired access rows (bounded growth); refresh rows persist.
            rows = [
                t for t in _read_rows(oauth_tokens_path(root))
                if not (t.get("kind") == "access" and _expired(t))
            ]
            common = {"grant_id": grant_id, "client_id": client_id, "scopes": scopes, "subject": subject}
            rows.append({"kind": "access", "hash": sha256_key(access), "expires_at": now + ACCESS_TTL, **common})
            rows.append({"kind": "refresh", "hash": sha256_key(refresh), "expires_at": None, **common})
            atomic_write_json(oauth_tokens_path(root), rows)
        return OAuthToken(
            access_token=access,
            refresh_token=refresh,
            expires_in=ACCESS_TTL,
            scope=" ".join(scopes) or None,
        )


_provider: EmergeOAuthProvider | None = None


def get_oauth_provider() -> EmergeOAuthProvider:
    """Process-wide singleton (it holds no state — root is read live)."""
    global _provider
    if _provider is None:
        _provider = EmergeOAuthProvider()
    return _provider
