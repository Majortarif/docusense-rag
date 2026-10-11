"""Plain data objects shared by the ingestion, indexing and inference layers."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Document:
    """A source document loaded from disk."""

    name: str
    text: str


@dataclass(frozen=True, slots=True)
class Chunk:
    """A retrievable unit of a document."""

    chunk_id: str
    text: str
    section: str
    source: str

    @property
    def embedding_text(self) -> str:
        """Text that is embedded: the heading breadcrumb gives each chunk its topical context."""
        return f"{self.section}\n\n{self.text}" if self.section else self.text


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """A chunk returned by the vector store together with its cosine similarity to the query."""

    chunk: Chunk
    score: float


@dataclass(frozen=True, slots=True)
class Generation:
    """The raw outcome of an answer generator, before guardrail validation.

    ``failure`` is set when the generator could not produce a usable answer at all
    (``"refusal"``, ``"truncated"`` or ``"invalid_output"``).
    """

    answerable: bool
    answer: str
    citations: tuple[str, ...] = ()
    tokens_used: int = 0
    failure: str | None = None


@dataclass(frozen=True, slots=True)
class SourceAttribution:
    chunk_id: str
    similarity_score: float
    text_snippet: str


@dataclass(frozen=True, slots=True)
class RAGResult:
    """Final pipeline result. ``outcome`` is ``"answered"`` or ``"fallback"``; ``reason`` says why."""

    answer: str
    sources: tuple[SourceAttribution, ...]
    tokens_used: int
    outcome: str
    reason: str
    top_score: float | None = field(default=None)
