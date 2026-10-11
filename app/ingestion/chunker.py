"""Deterministic, markdown-aware recursive character chunking.

Strategy
--------
1. **Structural split** – the document is split on markdown headings. Each section keeps its
   heading breadcrumb (e.g. ``2. Data Backup and Retention > 2.2 Retention periods``), which is
   stored on the chunk and prepended to the text that gets embedded.
2. **Recursive split** – a section longer than ``chunk_size`` is split on the coarsest separator
   that works (paragraph → line → sentence → word → character), so boundaries fall on natural
   breaks whenever possible.
3. **Greedy packing with overlap** – pieces are packed into chunks of at most ``chunk_size``
   characters. When a section spills into a new chunk, the new chunk starts with the trailing
   sentence(s) of the previous one (at most ``chunk_overlap`` characters), so a fact that sits on
   a boundary is retrievable from either side.

Overlap is never applied across sections: separate policy sections are independent topics, and
bleeding one into another would only dilute both embeddings.

The same input and parameters always produce the same chunks and the same ``chunk_NN`` ids.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.domain import Chunk, Document

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")

DEFAULT_SEPARATORS: tuple[str, ...] = ("\n\n", "\n", ". ", " ")


class MarkdownChunker:
    """Split documents into overlapping, heading-aware chunks."""

    def __init__(
        self,
        chunk_size: int = 800,
        chunk_overlap: int = 120,
        separators: Sequence[str] = DEFAULT_SEPARATORS,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if not 0 <= chunk_overlap < chunk_size:
            raise ValueError("chunk_overlap must be >= 0 and smaller than chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = tuple(separators)

    # ------------------------------------------------------------------ public API

    def chunk_documents(self, documents: Sequence[Document]) -> list[Chunk]:
        """Chunk every document and assign sequential, zero-padded ids (``chunk_00``, ``chunk_01`` …)."""
        drafts: list[tuple[str, str, str]] = []  # (text, section, source)
        for doc in documents:
            for section, body in self.split_sections(doc.text):
                drafts.extend((text, section, doc.name) for text in self.split_text(body))

        width = max(2, len(str(max(len(drafts) - 1, 0))))
        return [
            Chunk(chunk_id=f"chunk_{i:0{width}d}", text=text, section=section, source=source)
            for i, (text, section, source) in enumerate(drafts)
        ]

    def split_sections(self, text: str) -> list[tuple[str, str]]:
        """Split markdown into ``(heading breadcrumb, body)`` pairs.

        Headings inside code fences are ignored. When a document has exactly one level-1 heading,
        it is treated as the document title and left out of breadcrumbs: repeating the same title
        in every chunk would only make all chunk embeddings look alike.
        """
        lines = text.split("\n")
        headings = self._heading_lines(lines)
        level_one = [i for i, level in headings.items() if level == 1]
        title_line = level_one[0] if len(level_one) == 1 else None

        sections: list[tuple[str, str]] = []
        trail: list[tuple[int, str]] = []  # (level, title) of the current heading path
        body: list[str] = []
        doc_title = ""

        def flush() -> None:
            content = "\n".join(body).strip()
            if content:
                # Text directly under the document title (a preamble) is labelled with the title.
                sections.append((" > ".join(title for _, title in trail) or doc_title, content))
            body.clear()

        for number, line in enumerate(lines):
            match = _HEADING.match(line) if number in headings else None
            if match and number == title_line:
                flush()
                trail.clear()
                doc_title = match.group(2).strip()
            elif match:
                flush()
                level = len(match.group(1))
                while trail and trail[-1][0] >= level:
                    trail.pop()
                trail.append((level, match.group(2).strip()))
            else:
                body.append(line)
        flush()
        return sections

    def split_text(self, text: str) -> list[str]:
        """Split one section body into chunks of at most ``chunk_size`` characters."""
        text = text.strip()
        if not text:
            return []
        if len(text) <= self.chunk_size:
            return [text]
        return self._pack(self._split_recursive(text, self.separators))

    # ------------------------------------------------------------------ internals

    @staticmethod
    def _heading_lines(lines: Sequence[str]) -> dict[int, int]:
        """Map line number → heading level for every heading outside a code fence."""
        headings: dict[int, int] = {}
        in_fence = False
        for number, line in enumerate(lines):
            if _FENCE.match(line):
                in_fence = not in_fence
                continue
            match = None if in_fence else _HEADING.match(line)
            if match:
                headings[number] = len(match.group(1))
        return headings

    def _split_recursive(self, text: str, separators: Sequence[str]) -> list[str]:
        """Break ``text`` into pieces no longer than ``chunk_size``, keeping separators attached."""
        if len(text) <= self.chunk_size:
            return [text]
        for index, separator in enumerate(separators):
            if separator not in text:
                continue
            parts = text.split(separator)
            pieces: list[str] = []
            for position, part in enumerate(parts):
                piece = part + separator if position < len(parts) - 1 else part
                if not piece.strip():
                    continue
                if len(piece) <= self.chunk_size:
                    pieces.append(piece)
                else:
                    pieces.extend(self._split_recursive(piece, separators[index + 1 :]))
            return pieces
        # No separator left (e.g. one enormous token): fall back to a hard character split.
        return [text[i : i + self.chunk_size] for i in range(0, len(text), self.chunk_size)]

    def _pack(self, pieces: Sequence[str]) -> list[str]:
        """Greedily pack pieces into chunks, seeding each new chunk with a sentence-aligned overlap."""
        chunks: list[str] = []
        current = ""
        for piece in pieces:
            if current and len(current) + len(piece) > self.chunk_size:
                chunks.append(current.strip())
                current = self._overlap_tail(current)
                if len(current) + len(piece) > self.chunk_size:
                    current = ""
            current += piece
        if current.strip():
            chunks.append(current.strip())
        return chunks

    def _overlap_tail(self, text: str) -> str:
        """Return the trailing whole sentences of ``text`` that fit in ``chunk_overlap`` characters.

        If even the last sentence is longer than the overlap budget, the last ``chunk_overlap``
        characters are used instead, trimmed forward to a word boundary.
        """
        if self.chunk_overlap == 0:
            return ""
        sentences = [s for s in _SENTENCE_END.split(text.strip()) if s.strip()]
        tail: list[str] = []
        length = 0
        for sentence in reversed(sentences):
            added = len(sentence) + (1 if tail else 0)
            if length + added > self.chunk_overlap:
                break
            tail.insert(0, sentence)
            length += added
        if tail:
            return " ".join(tail) + " "
        window = text.strip()[-self.chunk_overlap :]
        space = window.find(" ")
        return (window[space + 1 :] if space != -1 else window) + " "
