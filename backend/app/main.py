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
from app.api.routes import jobs as jobs_route
from app.api.routes import predictions as predictions_route
from app.api.routes import projects as projects_route
from app.api.routes import reviewed as reviewed_route
from app.api.routes import schema as schema_route
from app.api.routes import upload as upload_route


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

if os.getenv("EMERGE_TEST_MODE") == "1":
    from app.api.routes import _test_stubs
    app.include_router(_test_stubs.router)
else:
    from app.api.routes import chat as chat_route
    app.include_router(chat_route.router)

app.include_router(upload_route.router)
app.include_router(projects_route.router)
app.include_router(docs_route.router)
app.include_router(predictions_route.router)
app.include_router(reviewed_route.router)
app.include_router(eval_route.router)
app.include_router(jobs_route.router)
app.include_router(schema_route.router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
