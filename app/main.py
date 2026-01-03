from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.assets.startup import init_assets_for_app

app = FastAPI(title="deception-ai", version="0.1.0")
app.include_router(router)

# Serve minimal web UI (no build step).
app.mount("/ui", StaticFiles(directory="app/static", html=True), name="ui")

# Expose raw CSVs for id->name lookups in the UI.
app.mount("/ui-assets", StaticFiles(directory="assets", html=False), name="ui-assets")


@app.on_event("startup")
async def _startup() -> None:
    init_assets_for_app()


@app.get("/")
async def _root() -> RedirectResponse:
    return RedirectResponse(url="/ui/")


@app.get("/info")
async def info() -> dict[str, str]:
    return {"name": "deception-ai", "version": "0.1.0"}
