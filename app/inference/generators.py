"""Answer generators: turn a question plus retrieved passages into a draft answer.

* ``AnthropicGenerator`` – Claude via the official Anthropic SDK, with structured outputs.
* ``ExtractiveGenerator`` – no LLM at all: returns the passage sentence(s) most similar to the
  question. Deterministic, free and offline; useful for demos without an API key and for tests.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any, Protocol

import anthropic
import numpy as np
from pydantic import BaseModel, ValidationError

from app.domain import Generation, RetrievedChunk
from app.indexing.embeddings import Embedder
from app.inference.prompts import ANSWER_SCHEMA, SYSTEM_PROMPT, build_user_prompt
from app.text_utils import split_sentences

logger = logging.getLogger(__name__)

#: Beta that enables ``fallbacks="default"``: if a safety classifier declines the request, the
#: API re-runs it on Anthropic's recommended fallback model inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class GenerationError(RuntimeError):
    """The LLM provider could not be reached or rejected the request (network, auth, quota)."""


class AnswerGenerator(Protocol):
    name: str

    def generate(self, question: str, passages: Sequence[RetrievedChunk]) -> Generation: ...


class _LLMAnswer(BaseModel):
    answerable: bool
    answer: str
    citations: list[str]


class AnthropicGenerator:
    """Grounded answer generation with Claude, constrained to a JSON schema."""

    name = "anthropic"

    def __init__(
        self,
        *,
        model: str,
        effort: str,
        max_tokens: int,
        enable_fallbacks: bool = True,
        timeout: float = 60.0,
        client: Any | None = None,
    ) -> None:
        self._model = model
        self._effort = effort
        self._max_tokens = max_tokens
        self._enable_fallbacks = enable_fallbacks
        self._client = client if client is not None else anthropic.Anthropic(timeout=timeout, max_retries=2)

    def generate(self, question: str, passages: Sequence[RetrievedChunk]) -> Generation:
        request: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": build_user_prompt(question, passages)}],
            "output_config": {
                "effort": self._effort,
                "format": {"type": "json_schema", "schema": ANSWER_SCHEMA},
            },
        }
        if self._enable_fallbacks:
            request["betas"] = [FALLBACK_BETA]
            request["fallbacks"] = "default"

        response = self._call(request)
        tokens = _total_tokens(response.usage)

        if response.stop_reason == "refusal":
            logger.warning("Model declined the request (refusal stop reason)")
            return Generation(answerable=False, answer="", tokens_used=tokens, failure="refusal")
        if response.stop_reason == "max_tokens":
            logger.warning("Model output hit max_tokens=%d and was truncated", self._max_tokens)
            return Generation(answerable=False, answer="", tokens_used=tokens, failure="truncated")

        text = "".join(block.text for block in response.content if block.type == "text")
        try:
            parsed = _LLMAnswer.model_validate(json.loads(text))
        except (ValueError, ValidationError):
            logger.warning("Model output was not valid answer JSON")
            return Generation(answerable=False, answer="", tokens_used=tokens, failure="invalid_output")

        return Generation(
            answerable=parsed.answerable,
            answer=parsed.answer.strip(),
            citations=tuple(dict.fromkeys(c.strip() for c in parsed.citations if c.strip())),
            tokens_used=tokens,
        )

    def _call(self, request: dict[str, Any]) -> Any:
        try:
            return self._client.beta.messages.create(**request)
        except anthropic.AuthenticationError as exc:
            raise GenerationError("LLM authentication failed: check ANTHROPIC_API_KEY") from exc
        except anthropic.RateLimitError as exc:
            raise GenerationError("LLM rate limit exceeded; retry later") from exc
        except anthropic.APIStatusError as exc:
            raise GenerationError(f"LLM provider returned HTTP {exc.status_code}") from exc
        except anthropic.APIConnectionError as exc:
            raise GenerationError("Could not reach the LLM provider") from exc
        except TypeError as exc:
            # The SDK raises TypeError when no credential source can be resolved at request time.
            if "authentication" in str(exc).lower():
                raise GenerationError(
                    "No Anthropic credentials configured: set ANTHROPIC_API_KEY or use LLM_PROVIDER=extractive"
                ) from exc
            raise


def _total_tokens(usage: Any) -> int:
    """Input + output tokens (output includes any thinking), plus prompt-cache traffic if present."""
    fields = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    return int(sum(getattr(usage, name, 0) or 0 for name in fields))


class ExtractiveGenerator:
    """LLM-free answers: the passage sentence(s) semantically closest to the question.

    The answer is a verbatim quote, so it cannot contain facts that are not in the document.
    It cannot, however, judge whether a closely related sentence truly answers the question;
    that judgement is what the LLM mode adds.
    """

    name = "extractive"

    def __init__(self, embedder: Embedder, max_sentences: int = 2, tie_margin: float = 0.06) -> None:
        self._embedder = embedder
        self._max_sentences = max_sentences
        self._tie_margin = tie_margin

    def generate(self, question: str, passages: Sequence[RetrievedChunk]) -> Generation:
        candidates = [
            (rank, position, passage.chunk.chunk_id, sentence)
            for rank, passage in enumerate(passages)
            for position, sentence in enumerate(split_sentences(passage.chunk.text))
            if len(sentence) >= 20  # skip fragments such as bare labels
        ]
        if not candidates:
            return Generation(answerable=False, answer="")

        query = self._embedder.embed_query(question)
        scores = self._embedder.embed_documents([c[3] for c in candidates]) @ query
        best = int(np.argmax(scores))
        best_rank, _, best_chunk, _ = candidates[best]

        # Add the next-best sentences from the same passage when they are nearly as relevant.
        chosen = [best]
        for idx in np.argsort(-scores, kind="stable"):
            idx = int(idx)
            if len(chosen) >= self._max_sentences:
                break
            if idx != best and candidates[idx][0] == best_rank and scores[idx] >= scores[best] - self._tie_margin:
                chosen.append(idx)

        chosen.sort(key=lambda i: candidates[i][1])  # keep document order
        answer = " ".join(candidates[i][3] for i in chosen)
        return Generation(answerable=True, answer=answer, citations=(best_chunk,))
