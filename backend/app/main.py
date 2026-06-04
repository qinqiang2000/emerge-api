import asyncio
import logging
import os
import time
from pathlib import Path

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
from app.api.routes import jobs as jobs_route
from app.api.routes import label_docs as label_docs_route
from app.api.routes import predictions as predictions_route
from app.api.routes import projects as projects_route
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
from app.api.routes import turns as turns_route

app.include_router(auth_route.router)

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
app.include_router(eval_route.router)
app.include_router(extract_lab_route.router)
app.include_router(jobs_route.router)
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


async def _prewarm_claude_cli_on_startup() -> None:
    """Page the bundled 207MB CLI Node binary into OS cache + prime Node JIT
    so the first chat after a backend boot doesn't pay ~5s of page-fault cost
    on `ClaudeSDKClient` enter. Runs as a background task — never blocks the
    healthz / chat routes from being served. Best-effort; failures are logged
    but don't poison startup (a bad OAuth token is a chat-time concern, not a
    boot-time one).
    """
    if os.getenv("EMERGE_TEST_MODE") == "1":
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
app.router.on_startup.append(_load_keystore_on_startup)
app.router.on_startup.append(_migrate_team_dirs_on_startup)
app.router.on_startup.append(_cleanup_staging_on_startup)
app.router.on_startup.append(_cleanup_orphan_projects_on_startup)
app.router.on_startup.append(_purge_trash_on_startup)
app.router.on_startup.append(_prewarm_claude_cli_on_startup)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
