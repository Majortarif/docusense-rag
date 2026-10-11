"""FastAPI application factory.

Run with ``uvicorn app.main:app``. Tests call :func:`create_app` with a pre-built pipeline.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app import __version__
from app.api.routes import router
from app.config import Settings, get_settings
from app.inference.generators import GenerationError
from app.inference.pipeline import RAGPipeline
from app.service import ServiceInfo, build_pipeline

logger = logging.getLogger("app")


def configure_logging(level: str) -> None:
    logging.basicConfig(level=level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(
    settings: Settings | None = None,
    *,
    pipeline: RAGPipeline | None = None,
    service_info: ServiceInfo | None = None,
) -> FastAPI:
    """Create the API. If ``pipeline`` is omitted it is built from ``settings`` at startup."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if pipeline is None:
            resolved = settings or get_settings()
            configure_logging(resolved.log_level)
            app.state.pipeline, app.state.service_info = build_pipeline(resolved)
            logger.info("DocuSense ready: %s", app.state.service_info)
        else:
            app.state.pipeline, app.state.service_info = pipeline, service_info
        yield

    app = FastAPI(
        title="DocuSense",
        version=__version__,
        description="Grounded question answering over internal documentation, with anti-hallucination guardrails.",
        lifespan=lifespan,
    )
    app.include_router(router)

    @app.exception_handler(GenerationError)
    async def _generation_error(_: Request, exc: GenerationError) -> JSONResponse:
        logger.error("LLM generation failed: %s", exc)
        return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content={"detail": str(exc)})

    return app


app = create_app()
