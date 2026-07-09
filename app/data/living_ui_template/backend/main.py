"""
Living UI Python Backend

FastAPI backend for Living UI projects.
Provides REST API for state management and data persistence.

To run manually:
    uvicorn main:app --port {{BACKEND_PORT}} --reload
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from routes import router
from system_routes import router as system_router
from files_routes import router as files_router
from engine import build_router as build_engine_router
from database import init_db
from logger import setup_logging, cleanup_old_logs
from pathlib import Path
import logging

# Initialize persistent file-based logging before anything else
setup_logging()
cleanup_old_logs(keep=20)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    logger.info("[Backend] Initializing database...")
    await init_db()
    logger.info("[Backend] Database initialized")
    yield
    logger.info("[Backend] Shutting down...")


app = FastAPI(
    title="{{PROJECT_NAME}} API",
    description="Backend API for {{PROJECT_NAME}} Living UI",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS configuration for frontend.
# Note: allow_credentials=True is invalid with a "*" origin per the CORS spec
# (and unnecessary — auth uses Bearer tokens in headers, not cookies).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# Diagnostic 500s (SYSTEM-MANAGED — do not remove). A bare "Internal Server
# Error" costs whole debug cycles; this handler puts the REAL exception into
# the response body so smoke tests, the frontend network log, and the agent
# see the root cause immediately.
# ============================================================================
import traceback

from fastapi.responses import JSONResponse

_BACKEND_DIR = str(Path(__file__).parent).lower()


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request, exc):
    where = None
    for frame in reversed(traceback.extract_tb(exc.__traceback__)):
        if _BACKEND_DIR in str(frame.filename).lower():
            where = f"{Path(frame.filename).name}:{frame.lineno} in {frame.name}"
            break
    detail = f"{type(exc).__name__}: {exc}"
    if where:
        detail += f" [at {where}]"
    logger.error(
        f"[Backend] Unhandled error on {request.method} {request.url.path}: {detail}"
    )
    return JSONResponse(status_code=500, content={"detail": detail})


# Include routes. Order matters for path resolution (first match wins):
#   1. system routes (state/action/ui-snapshot — never shadowed)
#   2. agent's custom routes (may intentionally override generated CRUD)
#   3. engine-generated CRUD from config/schema.json
app.include_router(system_router, prefix="/api")
app.include_router(files_router, prefix="/api")
app.include_router(router, prefix="/api")
app.include_router(build_engine_router(), prefix="/api")

# Auto-include additional routers from routes/ directory (if any)
import importlib
import pkgutil

_routes_dir = Path(__file__).parent / "routes"
if _routes_dir.exists() and (_routes_dir / "__init__.py").exists():
    for _imp, _mod, _pkg in pkgutil.iter_modules([str(_routes_dir)]):
        _m = importlib.import_module(f"routes.{_mod}")
        if hasattr(_m, "router"):
            app.include_router(_m.router, prefix="/api")


@app.get("/health")
async def health_check():
    """Health check endpoint for process management."""
    return {"status": "healthy", "project": "{{PROJECT_ID}}"}


# ============================================================================
# Frontend Console Log Capture (registered on app directly, not on router,
# so it survives agent rewrites of routes.py)
# ============================================================================
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

_FRONTEND_LOG_PATH = Path(__file__).parent / "logs" / "frontend_console.log"


class _FrontendLogEntry(BaseModel):
    level: str
    message: str
    timestamp: Optional[str] = None


class _FrontendLogBatch(BaseModel):
    entries: List[_FrontendLogEntry]


@app.post("/api/logs")
async def capture_frontend_logs(data: _FrontendLogBatch):
    """Capture frontend console logs for agent debugging."""
    _FRONTEND_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_FRONTEND_LOG_PATH, "a", encoding="utf-8") as f:
        for entry in data.entries:
            ts = entry.timestamp or datetime.utcnow().isoformat()
            f.write(f"{ts} | {entry.level.upper():<5} | {entry.message}\n")
    return {"status": "ok", "count": len(data.entries)}


# ============================================================================
# Serve frontend static files (built by Vite) — enables single-port access
# for LAN/tunnel sharing. Must be registered LAST (catch-all).
# ============================================================================
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

_DIST_DIR = Path(__file__).parent.parent / "dist"
_DIST_ASSETS = _DIST_DIR / "assets"
if _DIST_DIR.exists() and _DIST_ASSETS.exists():
    _CONFIG_DIR = Path(__file__).parent.parent / "config"

    @app.get("/config/manifest.json")
    async def serve_manifest():
        manifest = _CONFIG_DIR / "manifest.json"
        if manifest.exists():
            return FileResponse(manifest)
        return {"error": "manifest not found"}

    app.mount("/assets", StaticFiles(directory=str(_DIST_ASSETS)), name="assets")

    @app.get("/{path:path}")
    async def spa_fallback(path: str):
        file_path = _DIST_DIR / path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(_DIST_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port={{BACKEND_PORT}})
