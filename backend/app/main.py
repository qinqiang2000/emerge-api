import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load .env into os.environ so libraries that read directly from os.environ
# (claude_agent_sdk, google.genai, our provider factory) see CLAUDE_CODE_OAUTH_TOKEN,
# CLAUDE_PROXY, GOOGLE_API_KEY, ANTHROPIC_API_KEY. pydantic-settings reads .env separately.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from app.api.routes import docs as docs_route
from app.api.routes import eval as eval_route
from app.api.routes import experiments as experiments_route
from app.api.routes import export as export_route
from app.api.routes import jobs as jobs_route
from app.api.routes import pre_label as pre_label_route
from app.api.routes import predictions as predictions_route
from app.api.routes import projects as projects_route
from app.api.routes import models as models_route
from app.api.routes import prompts as prompts_route
from app.api.routes import publish as publish_route
from app.api.routes import reviewed as reviewed_route
from app.api.routes import schema as schema_route
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
)

from app.api.routes import chat as chat_route

if os.getenv("EMERGE_TEST_MODE") == "1":
    # Register stub POST /lab/chat *before* the real router. FastAPI matches in
    # registration order, so the stub wins for the SSE endpoint (no real LLM
    # call), while the real chat router still serves GET /lab/chats/{pid} and
    # GET /lab/chats/{pid}/{cid} — those read the filesystem and are safe.
    from app.api.routes import _test_stubs
    app.include_router(_test_stubs.router)
app.include_router(chat_route.router)

app.include_router(upload_route.router)
app.include_router(projects_route.router)
app.include_router(docs_route.router)
app.include_router(predictions_route.router)
app.include_router(prompts_route.router)
app.include_router(models_route.router)
app.include_router(experiments_route.router)
app.include_router(reviewed_route.router)
app.include_router(pre_label_route.router)
app.include_router(eval_route.router)
app.include_router(jobs_route.router)
app.include_router(schema_route.router)
app.include_router(export_route.router)
async def _load_keystore_on_startup() -> None:
    settings = get_settings()
    settings.workspace_root.mkdir(parents=True, exist_ok=True)
    get_keystore(settings.workspace_root)


async def _cleanup_staging_on_startup() -> None:
    from app.workspace.staging import cleanup_stale
    settings = get_settings()
    cleanup_stale(settings.workspace_root, max_age_hours=24.0)


async def _cleanup_orphan_projects_on_startup() -> None:
    from app.workspace.orphans import cleanup_orphan_projects
    settings = get_settings()
    cleanup_orphan_projects(settings.workspace_root)


app.include_router(publish_route.router)
app.router.on_startup.append(_load_keystore_on_startup)
app.router.on_startup.append(_cleanup_staging_on_startup)
app.router.on_startup.append(_cleanup_orphan_projects_on_startup)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
