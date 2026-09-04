"""FastAPI application factory for the Sentinel WebUI.

Creates and configures the FastAPI app with:
- All API routers (scenarios, runs, baselines)
- Static file serving for the frontend
- CORS middleware for local development
- Root route serving the SPA index.html
- ``scenario_dir`` stored on ``app.state`` for use by routers
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from sentinel.web.api.baselines import router as baselines_router
from sentinel.web.api.chaos import router as chaos_router
from sentinel.web.api.governance import router as governance_router
from sentinel.web.api.models import router as models_router
from sentinel.web.api.reports import router as reports_router
from sentinel.web.api.runs import router as runs_router
from sentinel.web.api.scenario_editor import router as scenario_editor_router
from sentinel.web.api.scenarios import router as scenarios_router

logger = logging.getLogger(__name__)

# Resolve paths relative to this file.
# This file lives at src/sentinel/web/app.py, so the static dir is
# one level up in the web package.
_WEB_DIR = Path(__file__).resolve().parent
_STATIC_DIR = _WEB_DIR / "static"
_PROJECT_ROOT = _WEB_DIR.parent.parent.parent
_CONFIG_FILE = _PROJECT_ROOT / "sentinel-web.yaml"

# Default CORS origins when no config file exists.
_DEFAULT_CORS_ORIGINS = ["*"]


def _get_version() -> str:
    """Read the version from sentinel.__version__."""
    import importlib

    try:
        mod = importlib.import_module("sentinel")
        return getattr(mod, "__version__", "0.0.0")
    except Exception:
        return "0.0.0"


def _load_cors_origins() -> list[str]:
    """Load CORS allowed origins from sentinel-web.yaml.

    Returns the ``web.cors_origins`` list from the config file, or
    ``_DEFAULT_CORS_ORIGINS`` if the file doesn't exist or has no
    CORS configuration.
    """
    if not _CONFIG_FILE.exists():
        return _DEFAULT_CORS_ORIGINS
    try:
        import yaml

        with open(_CONFIG_FILE, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        origins = data.get("web", {}).get("cors_origins")
        if isinstance(origins, list) and origins:
            return [str(o) for o in origins]
    except Exception:
        logger.debug("Failed to load CORS config from %s", _CONFIG_FILE, exc_info=True)
    return _DEFAULT_CORS_ORIGINS


def create_app(scenario_dir: str = "examples") -> FastAPI:
    """Create and configure the Sentinel WebUI FastAPI application.

    Args:
        scenario_dir: Default directory for scenario YAML/JSON files.
            Stored on ``app.state.scenario_dir`` so routers can
            access it.  Can be overridden per-request via query params.

    Returns:
        A fully configured FastAPI instance ready to serve.
    """
    version = _get_version()
    app = FastAPI(
        title="Sentinel WebUI",
        description="Agent Behavioral Testing Platform — Web Dashboard",
        version=version,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
    )

    # ── Store config on app.state ──
    app.state.scenario_dir = scenario_dir

    # ── CORS — configurable via sentinel-web.yaml ──
    cors_origins = _load_cors_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Mount API routers ──
    # Each router defines its own prefix (e.g. /api/scenarios),
    # so we include them at the root level.
    app.include_router(scenarios_router)
    app.include_router(scenario_editor_router)
    app.include_router(runs_router)
    app.include_router(baselines_router)
    app.include_router(models_router)
    app.include_router(chaos_router)
    app.include_router(reports_router)
    app.include_router(governance_router)

    # ── Health check ──
    @app.get("/api/health")
    async def health_check():
        """Simple health check endpoint for load balancers and monitoring."""
        return {"status": "ok", "version": version}

    # ── Root route → SPA index.html ──
    @app.get("/", response_class=HTMLResponse)
    async def serve_index():
        """Serve the single-page application's index.html.

        Falls back to a minimal placeholder if the static dir doesn't
        exist yet (e.g. before the frontend is built).
        """
        index_path = _STATIC_DIR / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        # Minimal placeholder so the API is still usable without a frontend
        return HTMLResponse(
            content=(
                "<html><body>"
                "<h1>Sentinel WebUI</h1>"
                "<p>API is running. Frontend not yet built.</p>"
                "<p><a href='/api/docs'>API Docs</a></p>"
                "</body></html>"
            )
        )

    # ── Static files (CSS, JS, images) ──
    # Mount at root level so the HTML can reference /css/ and /js/ directly.
    # Mount LAST so API routes take precedence over static file matching.
    if _STATIC_DIR.exists():
        from starlette.middleware.base import BaseHTTPMiddleware

        # Disable caching in development so the browser always fetches fresh JS/CSS.
        # In production, this should be enabled for performance.
        class NoCacheMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                response = await call_next(request)
                if request.url.path.startswith(("/css/", "/js/", "/img/")):
                    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                    response.headers["Pragma"] = "no-cache"
                    response.headers["Expires"] = "0"
                return response

        app.add_middleware(NoCacheMiddleware)

        css_dir = _STATIC_DIR / "css"
        js_dir = _STATIC_DIR / "js"
        img_dir = _STATIC_DIR / "img"
        if css_dir.exists():
            app.mount("/css", StaticFiles(directory=str(css_dir)), name="css")
        if js_dir.exists():
            app.mount("/js", StaticFiles(directory=str(js_dir)), name="js")
        if img_dir.exists():
            app.mount("/img", StaticFiles(directory=str(img_dir)), name="img")

    return app
