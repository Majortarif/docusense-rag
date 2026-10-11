"""Deterministic anti-hallucination guardrails.

They run in two places:

* **Before retrieval** – :func:`detect_prompt_injection` rejects questions that try to override
  the service's instructions, so no tokens are spent on them.
* **After generation** – :func:`validate_generation` accepts a draft answer only if the model said
  the question is answerable, cited at least one passage it was actually given, and every number in
  the answer appears in the cited passages. Anything else becomes the fallback message.

The similarity gate (no passage above the threshold → fallback, no LLM call) lives in the pipeline.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import NamedTuple

from app.domain import Generation, RetrievedChunk

_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    # Deliberately narrow: policy questions such as "Can a manager override the deployment
    # rules?" must still reach retrieval, so only instruction-hijacking phrasing is matched.
    for pattern in (
        r"\b(ignore|disregard|forget|override|bypass)\s+(?:(?:all|any|the|your|my|these|those)\s+)*"
        r"(?:(?:previous|prior|above|earlier|preceding|system|original)\s+)?(instructions?|prompts?|directives?)\b",
        r"\b(ignore|disregard)\s+(?:(?:all|any|the)\s+)?(context|documentation|documents?|passages?|sources?)\b",
        r"\b(system|developer)\s+(prompt|message)\b",
        r"\breveal\b.{0,40}\b(prompt|instructions)\b",
        r"\byou\s+are\s+now\b",
        r"\bpretend\s+(to\s+be|you\s+are)\b",
        r"\b(jailbreak|developer\s+mode)\b",
        r"\bwithout\s+(using|relying\s+on|looking\s+at)\s+the\s+(documents?|documentation|context|handbook|passages?)\b",
        r"\b(use|from)\s+your\s+(?:own\s+)?(?:general\s+)?(knowledge|training)\b",
        r"<\s*/?\s*(context|passage|question|system)\b",
    )
)

_NUMBER = re.compile(r"\d+(?:[.,:]\d+)*")
_CHUNK_REF = re.compile(r"\bchunk_\d+\b", re.IGNORECASE)
_FALLBACK_HINT = "does not contain sufficient information"


class GuardrailVerdict(NamedTuple):
    ok: bool
    reason: str


def detect_prompt_injection(question: str) -> str | None:
    """Return the matched pattern if the question looks like a prompt-injection attempt."""
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(question):
            return pattern.pattern
    return None


def extract_numbers(text: str) -> set[str]:
    """Numeric literals in ``text`` (thousands separators removed), ignoring chunk ids."""
    text = _CHUNK_REF.sub(" ", text)
    return {match.replace(",", "") for match in _NUMBER.findall(text)}


def ungrounded_numbers(answer: str, evidence: Sequence[str]) -> set[str]:
    """Numbers stated in ``answer`` that appear in none of the ``evidence`` texts."""
    supported: set[str] = set()
    for text in evidence:
        supported |= extract_numbers(text)
    return extract_numbers(answer) - supported


def validate_generation(generation: Generation, passages: Sequence[RetrievedChunk]) -> GuardrailVerdict:
    """Decide whether a draft answer is safe to return. Fails closed on anything unexpected."""
    if generation.failure:
        return GuardrailVerdict(False, generation.failure)
    if not generation.answerable or not generation.answer.strip():
        return GuardrailVerdict(False, "model_declined")
    if _FALLBACK_HINT in generation.answer.lower():
        return GuardrailVerdict(False, "model_declined")
    if not generation.citations:
        return GuardrailVerdict(False, "missing_citation")

    given = {p.chunk.chunk_id: p for p in passages}
    if any(chunk_id not in given for chunk_id in generation.citations):
        return GuardrailVerdict(False, "invalid_citation")

    evidence = [given[c].chunk.section + "\n" + given[c].chunk.text for c in generation.citations]
    if ungrounded_numbers(generation.answer, evidence):
        return GuardrailVerdict(False, "ungrounded_number")

    return GuardrailVerdict(True, "grounded")
