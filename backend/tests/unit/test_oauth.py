"""OAuth 2.0 authorization server (P2 — login-based custom connector).

Locks the emerge-specific glue around the `mcp.server.auth` scaffolding: the
`EmergeOAuthProvider` storage/rotation logic, the full DCR → /authorize →
consent → /token loop over HTTP, and that a minted access token routes the
`/mcp` transport to the owner's team workspace exactly like a PAT.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI, HTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.testclient import TestClient

from app.api.mcp_remote import _authenticate, _www_authenticate_header
from app.api.routes import oauth_consent as oauth_consent_route
from app.auth import store
from app.auth.bootstrap import bootstrap_superuser
from app.auth.oauth import ACCESS_PREFIX, REFRESH_PREFIX, get_oauth_provider
from app.config import get_settings
from app.workspace.paths import team_workspace_dir
from mcp.shared.auth import OAuthClientInformationFull


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    return verifier, challenge


async def _register_client(redirect_uri: str = "http://testserver/cb") -> OAuthClientInformationFull:
    """Persist a public (PKCE, no secret) client straight through the provider —
    the SDK RegistrationHandler is what mints id/secret; we only store."""
    client = OAuthClientInformationFull(
        client_id="client-" + secrets.token_hex(6),
        client_secret=None,
        redirect_uris=[redirect_uri],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
        client_name="Test Cowork",
    )
    await get_oauth_provider().register_client(client)
    return client


def _req(headers: dict | None = None, query: str = "") -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {"type": "http", "method": "POST", "path": "/mcp",
             "headers": raw, "query_string": query.encode()}

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


# --- provider storage / token lifecycle -------------------------------------

async def test_provider_authorize_to_token_roundtrip(workspace) -> None:
    su = await bootstrap_superuser(workspace, email="a@b.com", password="pw-12345678")
    provider = get_oauth_provider()
    client = await _register_client()
    _verifier, challenge = _pkce()

    # authorize → parks a txn, returns our consent URL
    from mcp.server.auth.provider import AuthorizationParams
    from pydantic import AnyUrl

    consent_url = await provider.authorize(
        client,
        AuthorizationParams(
            state="xyz", scopes=None, code_challenge=challenge,
            redirect_uri=AnyUrl("http://testserver/cb"),
            redirect_uri_provided_explicitly=True,
        ),
    )
    assert "/oauth/consent?txn=" in consent_url
    txn_id = parse_qs(urlparse(consent_url).query)["txn"][0]
    assert await provider.load_txn(txn_id) is not None

    # consent approved by the user → one-time code bound to subject
    redirect = await provider.complete_authorization(txn_id, subject=su.id)
    assert redirect.startswith("http://testserver/cb?")
    assert parse_qs(urlparse(redirect).query)["state"][0] == "xyz"
    code = parse_qs(urlparse(redirect).query)["code"][0]
    assert await provider.load_txn(txn_id) is None  # txn consumed

    # code → access + refresh, carrying the subject through
    auth_code = await provider.load_authorization_code(client, code)
    assert auth_code is not None and auth_code.subject == su.id
    token = await provider.exchange_authorization_code(client, auth_code)
    assert token.access_token.startswith(ACCESS_PREFIX)
    assert token.refresh_token.startswith(REFRESH_PREFIX)

    # code is one-time
    assert await provider.load_authorization_code(client, code) is None

    # access token verifies back to the subject
    access = await provider.load_access_token(token.access_token)
    assert access is not None and access.subject == su.id


async def test_provider_refresh_rotates_and_revoke_kills_grant(workspace) -> None:
    su = await bootstrap_superuser(workspace, email="a@b.com", password="pw-12345678")
    provider = get_oauth_provider()
    client = await _register_client()
    first = await provider._issue_tokens(client.client_id, [], su.id)

    refresh = await provider.load_refresh_token(client, first.refresh_token)
    assert refresh is not None
    rotated = await provider.exchange_refresh_token(client, refresh, [])
    # old refresh is dead, new pair works
    assert await provider.load_refresh_token(client, first.refresh_token) is None
    assert await provider.load_access_token(rotated.access_token) is not None

    # revoking by access token kills its sibling refresh too (same grant)
    access = await provider.load_access_token(rotated.access_token)
    await provider.revoke_token(access)
    assert await provider.load_access_token(rotated.access_token) is None
    assert await provider.load_refresh_token(client, rotated.refresh_token) is None


async def test_expired_txn_and_code_are_unusable(workspace, monkeypatch) -> None:
    await bootstrap_superuser(workspace, email="a@b.com", password="pw-12345678")
    provider = get_oauth_provider()
    client = await _register_client()
    _v, challenge = _pkce()
    from mcp.server.auth.provider import AuthorizationParams
    from pydantic import AnyUrl

    import app.auth.oauth as oauth_mod

    monkeypatch.setattr(oauth_mod, "_now", lambda: 1_000_000)
    url = await provider.authorize(client, AuthorizationParams(
        state=None, scopes=None, code_challenge=challenge,
        redirect_uri=AnyUrl("http://testserver/cb"), redirect_uri_provided_explicitly=True))
    txn_id = parse_qs(urlparse(url).query)["txn"][0]
    # jump past the txn TTL
    monkeypatch.setattr(oauth_mod, "_now", lambda: 1_000_000 + oauth_mod.TXN_TTL + 1)
    assert await provider.load_txn(txn_id) is None
    assert await provider.complete_authorization(txn_id, subject="u_x") is None


# --- /mcp bearer routing ----------------------------------------------------

async def test_oauth_access_token_routes_to_team(workspace) -> None:
    su = await bootstrap_superuser(workspace, email="a@b.com", password="pw-12345678")
    client = await _register_client()
    token = await get_oauth_provider()._issue_tokens(client.client_id, [], su.id)
    team = await store.get_team(workspace, su.active_team_id)
    expected = team_workspace_dir(workspace, team.slug or team.id)

    ws = await _authenticate(_req(headers={"Authorization": f"Bearer {token.access_token}"}))
    assert ws == expected


async def test_bogus_access_token_rejected(workspace) -> None:
    await bootstrap_superuser(workspace, email="a@b.com", password="pw-12345678")
    with pytest.raises(HTTPException) as ei:
        await _authenticate(_req(headers={"Authorization": f"Bearer {ACCESS_PREFIX}nope"}))
    assert ei.value.status_code == 401


async def test_www_authenticate_only_when_oauth_enabled(monkeypatch) -> None:
    monkeypatch.delenv("EMERGE_PUBLIC_BASE_URL", raising=False)
    assert _www_authenticate_header() is None
    monkeypatch.setenv("EMERGE_PUBLIC_BASE_URL", "https://emerge.example")
    hdr = _www_authenticate_header()
    assert hdr and b"oauth-protected-resource/mcp" in hdr[0][1]


# --- full HTTP loop: DCR → /authorize → consent → /token → use --------------

def _as_app() -> FastAPI:
    """A minimal app carrying the SDK auth-server routes + emerge's consent
    screen + session middleware — i.e. exactly what `main.py` mounts when a
    public origin is configured, isolated for the e2e."""
    from pydantic import AnyHttpUrl
    from mcp.server.auth.routes import create_auth_routes
    from mcp.server.auth.settings import ClientRegistrationOptions

    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret")
    app.include_router(oauth_consent_route.router)
    app.router.routes.extend(
        create_auth_routes(
            get_oauth_provider(),
            AnyHttpUrl("http://localhost"),
            client_registration_options=ClientRegistrationOptions(enabled=True),
        )
    )
    return app


async def test_full_oauth_login_loop(workspace, monkeypatch) -> None:
    monkeypatch.setenv("EMERGE_PUBLIC_BASE_URL", "http://localhost")
    su = await bootstrap_superuser(workspace, email="dev@team.com", password="pw-12345678")
    verifier, challenge = _pkce()
    redirect_uri = "http://testserver/cb"

    with TestClient(_as_app()) as c:
        # 1) Dynamic client registration (Claude does this automatically)
        reg = c.post("/register", json={
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "client_name": "Claude Cowork",
        })
        assert reg.status_code == 201, reg.text
        client_id = reg.json()["client_id"]

        # 2) /authorize → 302 to emerge's consent screen
        auth = c.get("/authorize", params={
            "response_type": "code", "client_id": client_id,
            "redirect_uri": redirect_uri, "code_challenge": challenge,
            "code_challenge_method": "S256", "state": "st8",
        }, follow_redirects=False)
        assert auth.status_code == 302
        txn = parse_qs(urlparse(auth.headers["location"]).query)["txn"][0]

        # 3) consent: log in + approve in one POST → 302 back to client w/ code
        consent = c.post("/oauth/consent", data={
            "txn": txn, "action": "approve",
            "email": "dev@team.com", "password": "pw-12345678",
        }, follow_redirects=False)
        assert consent.status_code == 302
        loc = urlparse(consent.headers["location"])
        assert loc.path == "/cb"
        q = parse_qs(loc.query)
        assert q["state"][0] == "st8"
        code = q["code"][0]

        # 4) /token: exchange code (+PKCE verifier) for tokens
        tok = c.post("/token", data={
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": redirect_uri, "client_id": client_id,
            "code_verifier": verifier,
        })
        assert tok.status_code == 200, tok.text
        access = tok.json()["access_token"]
        assert access.startswith(ACCESS_PREFIX)

    # 5) the issued token resolves to the owning user's team workspace
    resolved = await get_oauth_provider().load_access_token(access)
    assert resolved is not None and resolved.subject == su.id


async def test_consent_rejects_wrong_password(workspace, monkeypatch) -> None:
    monkeypatch.setenv("EMERGE_PUBLIC_BASE_URL", "http://localhost")
    await bootstrap_superuser(workspace, email="dev@team.com", password="pw-12345678")
    client = await _register_client()
    _v, challenge = _pkce()
    from mcp.server.auth.provider import AuthorizationParams
    from pydantic import AnyUrl

    url = await get_oauth_provider().authorize(client, AuthorizationParams(
        state=None, scopes=None, code_challenge=challenge,
        redirect_uri=AnyUrl("http://testserver/cb"), redirect_uri_provided_explicitly=True))
    txn = parse_qs(urlparse(url).query)["txn"][0]

    with TestClient(_as_app()) as c:
        bad = c.post("/oauth/consent", data={
            "txn": txn, "action": "approve",
            "email": "dev@team.com", "password": "wrong-pass",
        }, follow_redirects=False)
        assert bad.status_code == 200  # re-renders the consent page, not a redirect
        assert "incorrect" in bad.text.lower()
