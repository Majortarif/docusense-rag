from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from app.domain import Document, Generation, RetrievedChunk
from app.indexing.embeddings import HashingEmbedder
from app.indexing.index_builder import build_index
from app.indexing.vector_store import FaissVectorStore
from app.inference.pipeline import RAGPipeline
from app.ingestion.chunker import MarkdownChunker

PROJECT_ROOT = Path(__file__).resolve().parent.parent
POLICY_DOCUMENT = PROJECT_ROOT / "data" / "policies.md"

SAMPLE_MARKDOWN = """\
# Sample Handbook

Intro paragraph for the sample handbook.

## 1. Backups

### 1.1 Retention

All primary database backups are retained for a rolling period of 30 calendar days.
Monthly archives are kept for 12 months.

### 1.2 Encryption

Backups are encrypted at rest with AES-256.

## 2. Passwords

Passwords must be at least 14 characters long. Accounts lock after 10 failed attempts.
"""


class StubGenerator:
    """Returns a canned Generation and records what it was asked."""

    name = "stub"

    def __init__(self, generation: Generation | None = None) -> None:
        self.generation = generation
        self.calls: list[tuple[str, list[str]]] = []

    def generate(self, question: str, passages: Sequence[RetrievedChunk]) -> Generation:
        self.calls.append((question, [p.chunk.chunk_id for p in passages]))
        if self.generation is not None:
            return self.generation
        top = passages[0].chunk
        return Generation(answerable=True, answer=top.text.splitlines()[0], citations=(top.chunk_id,), tokens_used=42)


@pytest.fixture
def embedder() -> HashingEmbedder:
    return HashingEmbedder(dimension=512)


@pytest.fixture
def sample_document() -> Document:
    return Document(name="sample.md", text=SAMPLE_MARKDOWN)


@pytest.fixture
def store(embedder: HashingEmbedder, sample_document: Document) -> FaissVectorStore:
    return build_index([sample_document], MarkdownChunker(800, 120), embedder)


@pytest.fixture
def make_pipeline(store: FaissVectorStore, embedder: HashingEmbedder):
    # The lexical hashing embedder scores lower than a semantic model, hence the low default threshold.
    def _make(generator=None, threshold: float = 0.1, **kwargs) -> RAGPipeline:
        return RAGPipeline(
            store=store,
            embedder=embedder,
            generator=generator or StubGenerator(),
            top_k=3,
            similarity_threshold=threshold,
            **kwargs,
        )

    return _make
