import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import docs as docs_route
from app.api.routes import projects as projects_route
from app.api.routes import upload as upload_route


app = FastAPI(title="emerge", version="0.0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
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


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
