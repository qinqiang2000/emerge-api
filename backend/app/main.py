import asyncio
import logging
import os
import time
import warnings
from pathlib import Path

# Pydantic v2 retains a deprecated v1 `BaseModel.schema()` classmethod for compat.
# Our fields named "schema" shadow it harmlessly — suppress the noise.
warnings.filterwarnings("ignore", message='Field name "schema".*shadows', category=UserWarning)

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load .env into os.environ so libraries that read directly from os.environ
# (claude_agent_sdk, google.genai, our provider factory) see CLAUDE_CODE_OAUTH_TOKEN,
# CLAUDE_PROXY, GOOGLE_API_KEY, ANTHROPIC_API_KEY. pydantic-settings reads .env separately.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# The bundled Claude CLI is pinned by `claude-agent-sdk` in pyproject.toml, so
# the per-spawn `claude -v` handshake the SDK runs in `_check_claude_version`
# is pure overhead — skip it. See claude_agent_sdk/_internal/transport/subprocess_cli.py.
os.environ.setdefault("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")

from app.api.routes import bench as bench_route
from app.api.routes import docs as docs_route
from app.api.routes import eval as eval_route
from app.api.routes import experiments as experiments_route
from app.api.routes import export as export_route
from app.api.routes import extract_lab as extract_lab_route
from app.api.routes import history as history_route
from app.api.routes import jobs as jobs_route
from app.api.routes import label_docs as label_docs_route
from app.api.routes import config as config_route
from app.api.routes import predictions as predictions_route
from app.api.routes import projects as projects_route
from app.api.routes import ws as ws_route
from app.api.routes import match as match_route
from app.api.routes import models as models_route
from app.api.routes import prompts as prompts_route
from app.api.routes import publish as publish_route
from app.api.routes import reviewed as reviewed_route
from app.api.routes import schema as schema_route
from app.api.routes import textlayer as textlayer_route
from app.api.routes import translate as translate_route
from app.api.routes import upload as upload_route
from app.config import get_settings
from app.security.keys import get_keystore


app = FastAPI(title="emerge", version="0.0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5172", "http://127.0.0.1:5172",
        "http://localhost:5173", "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
    # Browser must send the session cookie cross-origin (Vite dev :5173 → API).
    allow_credentials=True,
)

# Persistent signed-cookie sessions (Users & Teams, 2026-06-03). Long-lived +
# rolling so closing the browser never forces a re-login; only explicit logout
# clears it. `request.session["uid"]` is the browser auth channel (the headless
# channel is the bearer PAT — see `app/auth/deps.py`).
from starlette.middleware.sessions import SessionMiddleware  # noqa: E402

_auth_settings = get_settings()
app.add_middleware(
    SessionMiddleware,
    secret_key=_auth_settings.secret_key,
    session_cookie="emerge_session",
    max_age=_auth_settings.session_max_age,
    same_site="lax",
    https_only=False,
)

from app.api.routes import auth as auth_route
from app.api.routes import chat as chat_route
from app.api.routes import oauth_consent as oauth_consent_route
from app.api.routes import turns as turns_route

app.include_router(auth_route.router)
# OAuth consent screen (P2). Self-managing session; safe to include always — the
# SDK authorization-server routes that drive it are mounted separately below, only
# when a public origin is configured.
app.include_router(oauth_consent_route.router)

if os.getenv("EMERGE_TEST_MODE") == "1":
    # Register the e2e stub turn routes *before* both the real ``turns_route``
    # and ``chat_route`` so they win on POST /lab/chats/{cid}/turns +
    # GET .../stream + .../cancel + GET .../turn_state. FastAPI matches in
    # registration order. The real chat router still serves GET /lab/chats/{pid}
    # and GET /lab/chats/{pid}/{cid} — those read the filesystem and are safe.
    # (Pre-followup-D this stubbed the legacy POST /lab/chat; the M11 frontend
    # cutover means the new turn surface is what the e2e exercises now.)
    from app.api.routes import _test_stubs
    app.include_router(_test_stubs.router)
# M11 Phase A: turn-as-resource routes MUST be registered before
# ``chat_route``. FastAPI matches handlers in include order; the
# ``GET /lab/chats/{slug}/{chat_id}`` route in chat.py is a two-segment
# pattern that would otherwise eat ``GET /lab/chats/{cid}/turn_state``
# (with ``slug=<cid>``, ``chat_id='turn_state'``) and bounce it through
# ``safe_chat_id`` as a 400. Pinning the turns router first means our
# specific patterns win.
app.include_router(turns_route.router)
app.include_router(chat_route.router)

app.include_router(upload_route.router)
app.include_router(projects_route.router)
app.include_router(ws_route.router)
app.include_router(match_route.router)
app.include_router(docs_route.router)
app.include_router(textlayer_route.router)
app.include_router(translate_route.router)
from app.api.routes import locate as locate_route  # noqa: E402

app.include_router(locate_route.router)
from app.api.routes import ground as ground_route  # noqa: E402

app.include_router(ground_route.router)
app.include_router(predictions_route.router)
app.include_router(prompts_route.router)
app.include_router(models_route.router)
app.include_router(experiments_route.router)
app.include_router(reviewed_route.router)
app.include_router(label_docs_route.router)
app.include_router(config_route.router)
app.include_router(eval_route.router)
app.include_router(extract_lab_route.router)
app.include_router(jobs_route.router)
app.include_router(history_route.router)
app.include_router(schema_route.router)
app.include_router(export_route.router)
app.include_router(bench_route.router)
async def _load_keystore_on_startup() -> None:
    settings = get_settings()
    settings.workspace_root.mkdir(parents=True, exist_ok=True)
    get_keystore(settings.workspace_root)


async def _migrate_team_dirs_on_startup() -> None:
    """Backfill Team.slug + rename legacy `teams/{id}/` → `teams/{slug}/` before
    anything walks or binds a team workspace this boot."""
    from app.workspace.migrate_team_dirs import migrate_team_dirs
    settings = get_settings()
    migrate_team_dirs(settings.workspace_root)


async def _cleanup_staging_on_startup() -> None:
    from app.workspace.staging import cleanup_stale
    settings = get_settings()
    cleanup_stale(settings.workspace_root, max_age_hours=24.0)


async def _cleanup_orphan_projects_on_startup() -> None:
    from app.workspace.orphans import cleanup_orphan_projects
    settings = get_settings()
    cleanup_orphan_projects(settings.workspace_root)


async def _purge_trash_on_startup() -> None:
    from app.workspace.trash import purge_all_trash
    settings = get_settings()
    purge_all_trash(settings.workspace_root)


async def _ensure_history_repos_on_startup() -> None:
    """Make each effective workspace a git repo with a baseline snapshot, so the
    version timeline exists from boot. Mode-aware: tenant mode repos each
    `teams/{slug}/` (NOT the true root — `_auth/`/`_keys.json` must never be
    committed); open mode repos the flat root. Best-effort / off-thread."""
    from app.auth import store
    from app.workspace.history import ensure_repo
    from app.workspace.paths import teams_root
    settings = get_settings()
    root = settings.workspace_root
    if await store.auth_configured(root):
        troot = teams_root(root)
        if troot.is_dir():
            for team_dir in troot.iterdir():
                if team_dir.is_dir() and not team_dir.name.startswith(("_", ".")):
                    await asyncio.to_thread(ensure_repo, team_dir)
    else:
        await asyncio.to_thread(ensure_repo, root)


# Idle catch-all: snapshot out-of-turn writes (UI review saves, headless route
# edits) that the turn-end commit never sees. 120s keeps history complete
# without churning git when idle (commit_all no-ops on a clean repo).
_HISTORY_CHECKPOINT_INTERVAL_S = 120.0


def _skip_background_startup() -> bool:
    """Suppress expensive/background startup side effects (the 207MB Claude CLI
    prewarm; the periodic history checkpoint loop) during tests. Two switches:
    `EMERGE_TEST_MODE` (the e2e harness, which also swaps in stub turn routes)
    and `EMERGE_DISABLE_PREWARM` (set by the pytest conftest, which deliberately
    runs WITHOUT test mode so the real turn routes are exercised — prewarm would
    otherwise spawn the CLI on every `with TestClient(app)` and crawl the suite)."""
    return (
        os.getenv("EMERGE_TEST_MODE") == "1"
        or os.getenv("EMERGE_DISABLE_PREWARM") == "1"
    )


async def _history_checkpoint_loop_on_startup() -> None:
    """Background loop: periodically commit any uncommitted workspace state so
    the version timeline captures non-chat edits too. Best-effort; tests skip it
    (they drive `checkpoint_all` directly)."""
    if _skip_background_startup():
        return
    from app.workspace.history import checkpoint_all
    log = logging.getLogger(__name__)

    async def _run() -> None:
        while True:
            try:
                await asyncio.sleep(_HISTORY_CHECKPOINT_INTERVAL_S)
                n = await asyncio.to_thread(checkpoint_all, get_settings().workspace_root)
                if n:
                    log.info("history checkpoint: committed %d workspace(s)", n)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — history never breaks the server
                log.warning("history checkpoint loop error", exc_info=True)

    asyncio.create_task(_run(), name="history-checkpoint")


async def _prewarm_claude_cli_on_startup() -> None:
    """Page the bundled 207MB CLI Node binary into OS cache + prime Node JIT
    so the first chat after a backend boot doesn't pay ~5s of page-fault cost
    on `ClaudeSDKClient` enter. Runs as a background task — never blocks the
    healthz / chat routes from being served. Best-effort; failures are logged
    but don't poison startup (a bad OAuth token is a chat-time concern, not a
    boot-time one).
    """
    if _skip_background_startup():
        return

    async def _run() -> None:
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
        log = logging.getLogger(__name__)
        t0 = time.monotonic()
        try:
            async with asyncio.timeout(15):
                async with ClaudeSDKClient(options=ClaudeAgentOptions()):
                    pass
            # warning-level so it surfaces in default uvicorn output — this is
            # an observability signal users want to see after backend boot.
            log.warning("claude-cli prewarm done in %.2fs", time.monotonic() - t0)
        except Exception as exc:  # noqa: BLE001 - prewarm is best-effort
            log.warning("claude-cli prewarm failed after %.2fs: %s",
                        time.monotonic() - t0, exc)

    asyncio.create_task(_run())


app.include_router(publish_route.router)
from app.api.routes import monitor as monitor_route  # noqa: E402

app.include_router(monitor_route.router)


async def _start_monitor_on_startup() -> None:
    """Auto-start the LLM availability watchdog when `EMERGE_MONITOR_ENABLED=1`.

    Decoupled from the rest of boot: a self-contained background task that only
    reads env + calls providers. Off by default (no behaviour change for
    existing deploys); always controllable at runtime via `/lab/monitor/*`
    regardless of this flag. Skipped under the test/prewarm-disable switches."""
    if _skip_background_startup():
        return
    from app.monitor.monitor import get_monitor

    monitor = get_monitor()
    if monitor.cfg.enabled:
        await monitor.start()


# Remote MCP (Streamable HTTP) — emerge as a Claude custom connector. Mounted at
# import time; the per-team session managers are built lazily on first request.
# NOT gated by `_skip_background_startup` (that switch conflates test + prewarm):
# the registry constructor is cheap (no provider / no I/O), so creating it in
# tests is harmless and no test hits `/mcp`. See `app/api/mcp_remote.py`.
from app.api.mcp_remote import RemoteMcpRegistry, make_mcp_asgi, remote_enabled  # noqa: E402

if remote_enabled():
    app.mount("/mcp", make_mcp_asgi(lambda: getattr(app.state, "mcp_registry", None)))

# OAuth 2.0 Authorization Server (P2) — `/authorize` `/token` `/register` (DCR)
# `/revoke` + `.well-known/oauth-authorization-server` come straight from the
# `mcp.server.auth` scaffolding; we only supply `EmergeOAuthProvider`. Plus the
# RFC 9728 protected-resource metadata that tells a Claude client where to find
# this AS. Mounted only when a public origin is set (it is the advertised issuer
# and consent-redirect base — see `Settings.public_base_url`); otherwise the P1
# `?token=` PAT URL remains the onboarding path. Appending Starlette routes onto
# `app.router.routes` (the FastMCP pattern) keeps these at the true root paths.
from app.auth.oauth import get_oauth_provider, oauth_enabled  # noqa: E402

if oauth_enabled():
    from pydantic import AnyHttpUrl  # noqa: E402
    from mcp.server.auth.routes import (  # noqa: E402
        create_auth_routes,
        create_protected_resource_routes,
    )
    from mcp.server.auth.settings import (  # noqa: E402
        ClientRegistrationOptions,
        RevocationOptions,
    )

    _oauth_base = get_settings().public_base_url.rstrip("/")
    _oauth_issuer = AnyHttpUrl(_oauth_base)
    app.router.routes.extend(
        create_auth_routes(
            get_oauth_provider(),
            _oauth_issuer,
            client_registration_options=ClientRegistrationOptions(enabled=True),
            revocation_options=RevocationOptions(enabled=True),
        )
    )
    app.router.routes.extend(
        create_protected_resource_routes(
            resource_url=AnyHttpUrl(f"{_oauth_base}/mcp"),
            authorization_servers=[_oauth_issuer],
            resource_name="emerge",
        )
    )


async def _start_remote_mcp_on_startup() -> None:
    if remote_enabled():
        app.state.mcp_registry = RemoteMcpRegistry()


async def _stop_remote_mcp_on_shutdown() -> None:
    registry = getattr(app.state, "mcp_registry", None)
    if registry is not None:
        await registry.shutdown()


app.router.on_startup.append(_load_keystore_on_startup)
app.router.on_startup.append(_migrate_team_dirs_on_startup)
app.router.on_startup.append(_cleanup_staging_on_startup)
app.router.on_startup.append(_cleanup_orphan_projects_on_startup)
app.router.on_startup.append(_purge_trash_on_startup)
app.router.on_startup.append(_ensure_history_repos_on_startup)
app.router.on_startup.append(_history_checkpoint_loop_on_startup)
app.router.on_startup.append(_prewarm_claude_cli_on_startup)
app.router.on_startup.append(_start_monitor_on_startup)
app.router.on_startup.append(_start_remote_mcp_on_startup)
app.router.on_shutdown.append(_stop_remote_mcp_on_shutdown)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
