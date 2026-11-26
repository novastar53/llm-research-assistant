"""Read-only FastAPI backend (spec section 5).

The repository path is fixed at server startup; no HTTP request can supply a
path, a Git command or any other mutation. Handlers are synchronous so the
blocking Git calls run in FastAPI's threadpool. Bind to loopback: this is a
local trusted-user tool, not a hardened multi-tenant server.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .errors import ScientistError
from .models import Experiment, ExperimentGraph, FileListing, TextFile
from .repository import ResearchRepository

logger = logging.getLogger(__name__)


def _default_static_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


#: scientist error code -> HTTP status (spec section 5.1 error table).
_STATUS_BY_CODE: dict[str, int] = {
    "not_found": 404,
    "invalid_argument": 400,
    "invalid_graph": 409,
    "invalid_manifest": 409,
    "ref_conflict": 409,
    "file_too_large": 413,
    "listing_too_large": 413,
    "unsupported_content": 415,
    "unsupported_path": 415,
    "git_timeout": 503,
    "git_error": 500,
    "invalid_repository": 500,
    "internal_error": 500,
}


def _error_body(code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"code": code, "message": message}}


def create_app(repo_path: str | Path, *, static_dir: str | Path | None = None) -> FastAPI:
    """Build the app around one research repository.

    Raises :class:`~scientist.errors.RepositoryError` at startup if the
    configured repository is invalid, so launch failures identify the cause.

    If a built frontend exists (``frontend/dist`` next to ``src/``, or an
    explicit *static_dir*), it is served from the same origin at non-/api
    paths; API routes always take precedence.
    """
    repo = ResearchRepository(repo_path)
    app = FastAPI(title="LLM Scientist Explorer")
    app.state.repo = repo
    dist = Path(static_dir) if static_dir is not None else _default_static_dir()

    @app.middleware("http")
    async def no_store(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        # Spec requires no-store for /api; static assets get it too so a
        # browser can never show a stale SPA build after a rebuild.
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ScientistError)
    async def scientist_error_handler(request: Request, exc: ScientistError) -> JSONResponse:
        return JSONResponse(
            _error_body(exc.code, exc.message),
            status_code=_STATUS_BY_CODE.get(exc.code, 500),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            _error_body("not_found", str(exc.detail)),
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = "; ".join(
            f"{'/'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        return JSONResponse(
            _error_body("validation_error", f"invalid request parameters: {details}"),
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error while serving %s %s", request.method, request.url.path)
        return JSONResponse(
            _error_body("internal_error", "an unexpected internal error occurred"),
            status_code=500,
        )

    @app.get("/api/graph", response_model=ExperimentGraph)
    def get_graph() -> ExperimentGraph:
        return repo.get_graph()

    @app.get("/api/experiments/{experiment_id}", response_model=Experiment)
    def get_experiment(experiment_id: str) -> Experiment:
        return repo.get_experiment(experiment_id)

    @app.get("/api/experiments/{experiment_id}/files", response_model=FileListing)
    def list_files(experiment_id: str, commit: str | None = None) -> FileListing:
        resolved = repo.resolve_revision(experiment_id, commit=commit)
        return FileListing(commit=resolved, files=repo.list_files(experiment_id, commit=resolved))

    @app.get("/api/experiments/{experiment_id}/file", response_model=TextFile)
    def read_file(experiment_id: str, path: str, commit: str | None = None) -> TextFile:
        return repo.read_text(experiment_id, path, commit=commit)

    # Mount last: API routes above always take precedence over the SPA. A
    # catch-all mount registered earlier would swallow /api/* requests.
    if dist.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")

    return app
