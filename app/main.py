from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
import logging

from app.api.routes import router
from app.assets.startup import init_assets_for_app

app = FastAPI(title="deception-ai", version="0.1.0")
app.include_router(router)
# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Serve minimal web UI (no build step).
# In some test/CI environments the static directory may be absent; don't fail import.
from pathlib import Path

_app_dir = Path(__file__).resolve().parent
_project_root = _app_dir.parent

_static_dir = _app_dir / "static"
if _static_dir.exists():
    app.mount("/ui", StaticFiles(directory=str(_static_dir), html=True), name="ui")

# Expose raw CSVs for id->name lookups in the UI.
# Use an absolute path so running from a different CWD (e.g., `pytest` from tests/) works.
_assets_dir = _project_root / "assets"
if _assets_dir.exists():
    app.mount("/ui-assets", StaticFiles(directory=str(_assets_dir), html=False), name="ui-assets")


@app.on_event("startup")
async def _startup() -> None:
    init_assets_for_app()


@app.get("/")
async def _root() -> RedirectResponse:
    return RedirectResponse(url="/ui/")


@app.get("/info")
async def info() -> dict[str, str]:
    return {"name": "deception-ai", "version": "0.1.0"}
