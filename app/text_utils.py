"""Small, dependency-free text helpers shared across layers."""

from __future__ import annotations

import re

_LIST_MARKER = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_INLINE_MARKUP = re.compile(r"\*\*|__|`")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])(?<!e\.g\.)(?<!i\.e\.)\s+(?=[A-Z0-9\"'(])")
_WORD = re.compile(r"[a-z0-9]+")

_STOPWORDS = frozenset(
    """
    a about above after again all also am an and any are as at be been before being below
    between both but by can could did do does doing down during each few for from further
    had has have having he her here hers him his how i if in into is it its itself just me
    more most my no nor not now of off on once only or other our ours out over own same she
    should so some such than that the their theirs them then there these they this those
    through to too under until up very was we were what when where which while who whom why
    will with would you your yours
    """.split()
)


def clean_markdown_line(line: str) -> str:
    """Strip list markers, blockquote markers and inline emphasis from a single line."""
    line = line.strip().lstrip(">").strip()
    line = _LIST_MARKER.sub("", line)
    return _INLINE_MARKUP.sub("", line).strip()


def split_sentences(text: str) -> list[str]:
    """Split markdown-ish text into sentences. List items are always separate sentences."""
    sentences: list[str] = []
    for raw_line in text.splitlines():
        line = clean_markdown_line(raw_line)
        if line:
            sentences.extend(part.strip() for part in _SENTENCE_BOUNDARY.split(line) if part.strip())
    return sentences


def content_terms(text: str) -> set[str]:
    """Lower-cased words that carry meaning (stopwords removed)."""
    return {word for word in _WORD.findall(text.lower()) if word not in _STOPWORDS}


def truncate_at_word(text: str, max_chars: int) -> str:
    """Shorten ``text`` to at most ``max_chars`` characters without cutting a word in half."""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:")
