"""An embedded FAISS vector store with on-disk persistence."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

import faiss
import numpy as np

from app.domain import Chunk, RetrievedChunk

INDEX_FILE = "index.faiss"
CHUNKS_FILE = "chunks.json"


class FaissVectorStore:
    """Exact cosine-similarity search over normalised vectors (``IndexFlatIP``).

    A flat index is the right tool at this scale: a policy handbook yields tens to a few
    thousand chunks, where exact search takes well under a millisecond and needs no training
    or recall tuning (unlike IVF/HNSW).
    """

    def __init__(self, dimension: int) -> None:
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self._index = faiss.IndexFlatIP(dimension)
        self._chunks: list[Chunk] = []

    @property
    def dimension(self) -> int:
        return int(self._index.d)

    @property
    def chunks(self) -> tuple[Chunk, ...]:
        return tuple(self._chunks)

    def __len__(self) -> int:
        return len(self._chunks)

    def add(self, chunks: Sequence[Chunk], vectors: np.ndarray) -> None:
        """Add chunks with their (already normalised) embeddings, row-aligned."""
        vectors = np.ascontiguousarray(vectors, dtype=np.float32)
        if vectors.ndim != 2 or vectors.shape[0] != len(chunks):
            raise ValueError(f"Expected {len(chunks)} vectors, got array of shape {vectors.shape}")
        if vectors.shape[1] != self.dimension:
            raise ValueError(f"Vector dimension {vectors.shape[1]} != index dimension {self.dimension}")
        self._index.add(vectors)
        self._chunks.extend(chunks)

    def search(self, query_vector: np.ndarray, k: int) -> list[RetrievedChunk]:
        """Return up to ``k`` chunks ordered by descending cosine similarity."""
        query = np.ascontiguousarray(query_vector, dtype=np.float32).reshape(1, -1)
        if query.shape[1] != self.dimension:
            raise ValueError(f"Query dimension {query.shape[1]} != index dimension {self.dimension}")
        if not self._chunks or k <= 0:
            return []
        scores, ids = self._index.search(query, min(k, len(self._chunks)))
        return [
            RetrievedChunk(chunk=self._chunks[idx], score=float(score))
            for score, idx in zip(scores[0], ids[0], strict=True)
            if idx != -1
        ]

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(directory / INDEX_FILE))
        payload = [asdict(chunk) for chunk in self._chunks]
        (directory / CHUNKS_FILE).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, directory: Path) -> FaissVectorStore:
        index = faiss.read_index(str(directory / INDEX_FILE))
        chunks = [Chunk(**item) for item in json.loads((directory / CHUNKS_FILE).read_text(encoding="utf-8"))]
        if index.ntotal != len(chunks):
            raise ValueError(f"Corrupt index: {index.ntotal} vectors but {len(chunks)} chunks")
        store = cls(index.d)
        store._index = index
        store._chunks = chunks
        return store
