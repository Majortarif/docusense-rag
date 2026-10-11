"""Composition root: wire settings into a ready-to-serve pipeline."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from app.config import Settings
from app.indexing.embeddings import Embedder, create_embedder
from app.indexing.index_builder import IndexManifest, load_or_build_index
from app.inference.generators import AnswerGenerator, AnthropicGenerator, ExtractiveGenerator
from app.inference.pipeline import RAGPipeline
from app.ingestion.chunker import MarkdownChunker

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ServiceInfo:
    """Static facts about the running service, exposed by the health endpoint."""

    documents: tuple[str, ...]
    chunks: int
    embedding_model: str
    llm_provider: str
    llm_model: str | None
    similarity_threshold: float
    top_k: int


def create_generator(settings: Settings, embedder: Embedder) -> AnswerGenerator:
    if settings.llm_provider == "extractive":
        return ExtractiveGenerator(embedder)
    if not any(os.environ.get(var) for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE")):
        logger.warning(
            "LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set; queries that reach the LLM will fail "
            "unless an `ant auth login` profile is available. Use LLM_PROVIDER=extractive to run without a key."
        )
    return AnthropicGenerator(
        model=settings.anthropic_model,
        effort=settings.anthropic_effort,
        max_tokens=settings.anthropic_max_tokens,
        enable_fallbacks=settings.anthropic_fallbacks,
        timeout=settings.llm_timeout_seconds,
    )


def build_pipeline(settings: Settings) -> tuple[RAGPipeline, ServiceInfo]:
    """Load (or build) the index and assemble the query pipeline."""
    embedder = create_embedder(settings)
    chunker = MarkdownChunker(settings.chunk_size, settings.chunk_overlap)
    store, manifest = load_or_build_index(settings.document_path, settings.index_dir, chunker, embedder)
    generator = create_generator(settings, embedder)
    pipeline = RAGPipeline(
        store=store,
        embedder=embedder,
        generator=generator,
        top_k=settings.top_k,
        similarity_threshold=settings.similarity_threshold,
        max_context_tokens=settings.max_context_tokens,
        block_prompt_injection=settings.block_prompt_injection,
    )
    return pipeline, describe(pipeline, manifest, settings)


def describe(pipeline: RAGPipeline, manifest: IndexManifest, settings: Settings) -> ServiceInfo:
    return ServiceInfo(
        documents=manifest.documents,
        chunks=len(pipeline.store),
        embedding_model=manifest.embedding_model,
        llm_provider=pipeline.generator.name,
        llm_model=settings.anthropic_model if pipeline.generator.name == "anthropic" else None,
        similarity_threshold=pipeline.similarity_threshold,
        top_k=pipeline.top_k,
    )
