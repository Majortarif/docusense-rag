"""HTTP routes. Thin by design: validation here, all logic in the pipeline."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api.schemas import ErrorResponse, HealthResponse, QueryRequest, QueryResponse, Source
from app.inference.pipeline import RAGPipeline
from app.service import ServiceInfo

router = APIRouter(prefix="/api")


def get_pipeline(request: Request) -> RAGPipeline:
    pipeline = getattr(request.app.state, "pipeline", None)
    if pipeline is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Index is not ready")
    return pipeline


def get_service_info(request: Request) -> ServiceInfo:
    info = getattr(request.app.state, "service_info", None)
    if info is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Index is not ready")
    return info


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Answer a question from the ingested documentation",
    responses={502: {"model": ErrorResponse, "description": "The LLM provider failed"}},
)
def query(
    payload: QueryRequest,
    response: Response,
    pipeline: Annotated[RAGPipeline, Depends(get_pipeline)],
) -> QueryResponse:
    result = pipeline.answer(payload.question)
    # Diagnostics live in headers so the response body matches the contract exactly.
    response.headers["X-DocuSense-Outcome"] = result.outcome
    response.headers["X-DocuSense-Reason"] = result.reason
    return QueryResponse(
        answer=result.answer,
        sources=[
            Source(chunk_id=s.chunk_id, similarity_score=round(s.similarity_score, 2), text_snippet=s.text_snippet)
            for s in result.sources
        ],
        tokens_used=result.tokens_used,
    )


@router.get("/health", response_model=HealthResponse, summary="Liveness and index information")
def health(info: Annotated[ServiceInfo, Depends(get_service_info)]) -> HealthResponse:
    data = asdict(info)
    data["documents"] = list(info.documents)
    return HealthResponse(status="ok", **data)
