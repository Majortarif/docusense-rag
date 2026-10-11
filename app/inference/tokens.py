"""Token budgeting for the prompt context.

Budgeting uses a conservative character-based estimate (~4 characters per token for English
prose). It is only used to decide how many passages fit in the prompt; the ``tokens_used``
reported by the API comes from the LLM provider's own usage accounting.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from app.domain import RetrievedChunk

CHARS_PER_TOKEN = 4
#: Approximate per-passage overhead of the XML wrapper and attributes in the prompt.
PASSAGE_OVERHEAD_TOKENS = 25


def estimate_tokens(text: str) -> int:
    """Rough token count for budgeting (rounds up)."""
    return math.ceil(len(text) / CHARS_PER_TOKEN) if text else 0


def pack_context(passages: Sequence[RetrievedChunk], max_tokens: int) -> list[RetrievedChunk]:
    """Keep the highest-scoring passages that fit within ``max_tokens``.

    ``passages`` must already be sorted best-first. The best passage is always kept so that a
    single oversized chunk can never produce an empty context.
    """
    selected: list[RetrievedChunk] = []
    used = 0
    for passage in passages:
        cost = estimate_tokens(passage.chunk.section + passage.chunk.text) + PASSAGE_OVERHEAD_TOKENS
        if selected and used + cost > max_tokens:
            break
        selected.append(passage)
        used += cost
    return selected
