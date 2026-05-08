from fastapi import FastAPI

app = FastAPI(title="emerge", version="0.0.1")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
