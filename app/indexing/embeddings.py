"""Embedding providers.

* ``FastEmbedEmbedder`` – the default. Runs ``BAAI/bge-small-en-v1.5`` locally through ONNX Runtime
  (no PyTorch, no API key, no per-call cost). Queries and passages are embedded asymmetrically,
  as the model was trained.
* ``HashingEmbedder`` – a deterministic, dependency-free lexical embedder (feature hashing). It is
  **not semantic**; it exists so unit tests and air-gapped smoke tests run without a model download.

Every provider returns L2-normalised ``float32`` vectors, so inner product == cosine similarity.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import numpy as np

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)


class Embedder(Protocol):
    """Anything that can turn text into normalised vectors."""

    @property
    def model_id(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...


def l2_normalize(vectors: np.ndarray) -> np.ndarray:
    """Normalise rows to unit length (zero rows are left as zeros)."""
    vectors = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    return vectors / np.where(norms == 0, 1.0, norms)


class FastEmbedEmbedder:
    """Local ONNX sentence embeddings via the ``fastembed`` library."""

    def __init__(self, model_name: str, cache_dir: Path | None = None, batch_size: int = 32) -> None:
        from fastembed import TextEmbedding  # imported lazily: heavy, and unused by the hashing provider

        logger.info("Loading embedding model %s", model_name)
        self._model_name = model_name
        self._batch_size = batch_size
        self._model = TextEmbedding(model_name=model_name, cache_dir=str(cache_dir) if cache_dir else None)
        self._dimension = int(self.embed_query("dimension probe").shape[0])

    @property
    def model_id(self) -> str:
        return f"fastembed:{self._model_name}"

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dimension), dtype=np.float32)
        vectors = np.asarray(list(self._model.passage_embed(list(texts), batch_size=self._batch_size)))
        return l2_normalize(vectors)

    def embed_query(self, text: str) -> np.ndarray:
        vector = np.asarray(next(iter(self._model.query_embed(text))))
        return l2_normalize(vector)


class HashingEmbedder:
    """Deterministic bag-of-words embeddings using signed feature hashing (unigrams + bigrams)."""

    _TOKEN = re.compile(r"[a-z0-9]+")

    def __init__(self, dimension: int = 1024) -> None:
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self._dimension = dimension

    @property
    def model_id(self) -> str:
        return f"hashing:{self._dimension}"

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dimension), dtype=np.float32)
        return l2_normalize(np.stack([self._vectorize(text) for text in texts]))

    def embed_query(self, text: str) -> np.ndarray:
        return l2_normalize(self._vectorize(text))

    def _vectorize(self, text: str) -> np.ndarray:
        tokens = self._TOKEN.findall(text.lower())
        features = tokens + [f"{a} {b}" for a, b in zip(tokens, tokens[1:], strict=False)]
        vector = np.zeros(self._dimension, dtype=np.float32)
        for feature, count in Counter(features).items():
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "little")
            sign = 1.0 if value & 1 else -1.0
            vector[(value >> 1) % self._dimension] += sign * (1.0 + math.log(count))
        return vector


def create_embedder(settings: Settings) -> Embedder:
    """Build the embedder selected by ``EMBEDDING_PROVIDER``."""
    if settings.embedding_provider == "hashing":
        return HashingEmbedder()
    return FastEmbedEmbedder(settings.embedding_model, cache_dir=settings.embedding_cache_dir)
