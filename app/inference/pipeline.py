"""The query pipeline: guard → retrieve → gate → generate → validate → attribute."""

from __future__ import annotations

import logging
import time

from app.config import FALLBACK_MESSAGE
from app.domain import RAGResult, RetrievedChunk, SourceAttribution
from app.indexing.embeddings import Embedder
from app.indexing.vector_store import FaissVectorStore
from app.inference.generators import AnswerGenerator
from app.inference.guardrails import detect_prompt_injection, validate_generation
from app.inference.tokens import pack_context
from app.text_utils import content_terms, split_sentences, truncate_at_word

logger = logging.getLogger(__name__)

SNIPPET_MAX_CHARS = 220


class RAGPipeline:
    """Answers questions strictly from the indexed documents, or returns :data:`FALLBACK_MESSAGE`."""

    def __init__(
        self,
        *,
        store: FaissVectorStore,
        embedder: Embedder,
        generator: AnswerGenerator,
        top_k: int = 4,
        similarity_threshold: float = 0.65,
        max_context_tokens: int = 1500,
        block_prompt_injection: bool = True,
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.generator = generator
        self.top_k = top_k
        self.similarity_threshold = similarity_threshold
        self.max_context_tokens = max_context_tokens
        self.block_prompt_injection = block_prompt_injection

    def retrieve(self, question: str) -> list[RetrievedChunk]:
        """Top-k chunks for ``question`` (no threshold applied)."""
        return self.store.search(self.embedder.embed_query(question), self.top_k)

    def answer(self, question: str) -> RAGResult:
        started = time.perf_counter()
        question = " ".join(question.split())
        result = self._answer(question)
        logger.info(
            "query outcome=%s reason=%s top_score=%s sources=%d tokens=%d latency_ms=%.0f",
            result.outcome,
            result.reason,
            f"{result.top_score:.3f}" if result.top_score is not None else "n/a",
            len(result.sources),
            result.tokens_used,
            (time.perf_counter() - started) * 1000,
        )
        return result

    def _answer(self, question: str) -> RAGResult:
        if self.block_prompt_injection and detect_prompt_injection(question):
            return _fallback("prompt_injection")

        hits = self.retrieve(question)
        top_score = hits[0].score if hits else None
        relevant = [hit for hit in hits if hit.score >= self.similarity_threshold]
        if not relevant:
            # Nothing in the document is close enough: answer deterministically, spend no LLM tokens.
            return _fallback("low_similarity", top_score=top_score)

        passages = pack_context(relevant, self.max_context_tokens)
        generation = self.generator.generate(question, passages)
        verdict = validate_generation(generation, passages)
        if not verdict.ok:
            return _fallback(verdict.reason, tokens_used=generation.tokens_used, top_score=top_score)

        cited = set(generation.citations)
        sources = tuple(
            SourceAttribution(
                chunk_id=p.chunk.chunk_id,
                similarity_score=p.score,
                text_snippet=make_snippet(p.chunk.text, generation.answer, question),
            )
            for p in passages
            if p.chunk.chunk_id in cited
        )
        return RAGResult(
            answer=generation.answer,
            sources=sources,
            tokens_used=generation.tokens_used,
            outcome="answered",
            reason=verdict.reason,
            top_score=top_score,
        )


def _fallback(reason: str, *, tokens_used: int = 0, top_score: float | None = None) -> RAGResult:
    return RAGResult(
        answer=FALLBACK_MESSAGE,
        sources=(),
        tokens_used=tokens_used,
        outcome="fallback",
        reason=reason,
        top_score=top_score,
    )


def make_snippet(chunk_text: str, answer: str, question: str, max_chars: int = SNIPPET_MAX_CHARS) -> str:
    """The sentence of a chunk that best supports the answer, as a short ``...excerpt...``."""
    sentences = split_sentences(chunk_text)
    if not sentences:
        return "..." + truncate_at_word(chunk_text.strip(), max_chars) + "..."
    answer_terms = content_terms(answer)
    question_terms = content_terms(question)
    best = max(
        sentences,
        key=lambda s: (len(content_terms(s) & answer_terms), len(content_terms(s) & question_terms)),
    )
    return "..." + truncate_at_word(best, max_chars).rstrip(".") + "..."
