from fastapi import FastAPI
from app.api.routes import router
from app.assets.startup import init_assets_for_app

app = FastAPI(title="deception-ai", version="0.1.0")
app.include_router(router)


@app.on_event("startup")
async def _startup() -> None:
    init_assets_for_app()


@app.get("/info")
async def info() -> dict[str, str]:
    return {"name": "deception-ai", "version": "0.1.0"}
