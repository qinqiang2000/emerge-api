from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import chat as chat_route


app = FastAPI(title="emerge", version="0.0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_route.router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
