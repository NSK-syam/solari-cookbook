"""Vercel Python Function entrypoint for the existing FastAPI application."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = PROJECT_ROOT / "backend" / "src"

sys.path.insert(0, str(BACKEND_SRC))
os.environ.setdefault("SEPTIC_SENTINEL_MODE", "fixture")
os.environ.setdefault("SEPTIC_SENTINEL_DB_PATH", "/tmp/closing-rescue.sqlite3")
os.environ.setdefault(
    "SEPTIC_SENTINEL_FIXTURE_ROOT", str(PROJECT_ROOT / "fixtures" / "cases")
)
os.environ.setdefault(
    "SEPTIC_SENTINEL_SOLARI_ARTIFACT_DIR", "/tmp/closing-rescue-artifacts"
)

from septic_sentinel.api import app

FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
FRONTEND_ROOT = FRONTEND_DIST.resolve()
FRONTEND_INDEX = FRONTEND_DIST / "index.html"
FRONTEND_ASSETS = FRONTEND_DIST / "assets"

if FRONTEND_ASSETS.is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_ASSETS),
        name="closing-rescue-assets",
    )


@app.get("/", include_in_schema=False, response_class=FileResponse)
async def frontend_root() -> FileResponse:
    """Serve the built React entrypoint from the full-stack Vercel function."""
    if not FRONTEND_INDEX.is_file():
        raise HTTPException(status_code=503, detail="Frontend build is unavailable")
    return FileResponse(FRONTEND_INDEX)


@app.get("/{frontend_path:path}", include_in_schema=False, response_class=FileResponse)
async def frontend_fallback(frontend_path: str) -> FileResponse:
    """Serve public files or the SPA entrypoint without masking missing APIs."""
    if frontend_path == "api" or frontend_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")

    requested_file = (FRONTEND_ROOT / frontend_path).resolve()
    try:
        requested_file.relative_to(FRONTEND_ROOT)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Not Found") from exc

    if requested_file.is_file():
        return FileResponse(requested_file)
    if not FRONTEND_INDEX.is_file():
        raise HTTPException(status_code=503, detail="Frontend build is unavailable")
    return FileResponse(FRONTEND_INDEX)

__all__ = ["app"]
