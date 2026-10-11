"""Build the vector index, or reuse a persisted one when nothing relevant has changed."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from app.domain import Document
from app.indexing.embeddings import Embedder
from app.indexing.vector_store import FaissVectorStore
from app.ingestion.chunker import MarkdownChunker
from app.ingestion.loader import fingerprint, load_documents

logger = logging.getLogger(__name__)

MANIFEST_FILE = "manifest.json"
MANIFEST_VERSION = 1


@dataclass(frozen=True)
class IndexManifest:
    """Everything that, if changed, invalidates a persisted index."""

    version: int
    documents_sha256: str
    documents: tuple[str, ...]
    embedding_model: str
    dimension: int
    chunk_size: int
    chunk_overlap: int
    num_chunks: int = 0

    def same_build_as(self, other: IndexManifest) -> bool:
        ignore = {"num_chunks"}
        mine = {k: v for k, v in asdict(self).items() if k not in ignore}
        theirs = {k: v for k, v in asdict(other).items() if k not in ignore}
        return mine == theirs


def build_index(documents: list[Document], chunker: MarkdownChunker, embedder: Embedder) -> FaissVectorStore:
    """Chunk and embed ``documents`` into a fresh in-memory store."""
    chunks = chunker.chunk_documents(documents)
    vectors = embedder.embed_documents([chunk.embedding_text for chunk in chunks])
    store = FaissVectorStore(embedder.dimension)
    store.add(chunks, vectors)
    return store


def load_or_build_index(
    document_path: Path,
    index_dir: Path,
    chunker: MarkdownChunker,
    embedder: Embedder,
    *,
    force_rebuild: bool = False,
) -> tuple[FaissVectorStore, IndexManifest]:
    """Return a ready vector store, reusing ``index_dir`` when its manifest still matches.

    The index is rebuilt automatically when the documents, the embedding model or the chunking
    parameters change. Persisting is best-effort: if ``index_dir`` is not writable the service
    still starts with an in-memory index.
    """
    documents = load_documents(document_path)
    expected = IndexManifest(
        version=MANIFEST_VERSION,
        documents_sha256=fingerprint(documents),
        documents=tuple(doc.name for doc in documents),
        embedding_model=embedder.model_id,
        dimension=embedder.dimension,
        chunk_size=chunker.chunk_size,
        chunk_overlap=chunker.chunk_overlap,
    )

    if not force_rebuild:
        cached = _try_load(index_dir, expected)
        if cached is not None:
            store, manifest = cached
            logger.info("Loaded persisted index from %s (%d chunks)", index_dir, len(store))
            return store, manifest

    logger.info("Building index for %s", ", ".join(expected.documents))
    store = build_index(documents, chunker, embedder)
    manifest = IndexManifest(**{**asdict(expected), "num_chunks": len(store)})
    try:
        store.save(index_dir)
        (index_dir / MANIFEST_FILE).write_text(json.dumps(asdict(manifest), indent=2), encoding="utf-8")
        logger.info("Persisted index with %d chunks to %s", len(store), index_dir)
    except OSError as exc:
        logger.warning("Could not persist index to %s (%s); continuing in memory", index_dir, exc)
    return store, manifest


def _try_load(index_dir: Path, expected: IndexManifest) -> tuple[FaissVectorStore, IndexManifest] | None:
    manifest_path = index_dir / MANIFEST_FILE
    if not manifest_path.exists():
        return None
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        raw["documents"] = tuple(raw.get("documents", ()))
        manifest = IndexManifest(**raw)
        if not manifest.same_build_as(expected):
            logger.info("Persisted index is stale (documents or configuration changed); rebuilding")
            return None
        store = FaissVectorStore.load(index_dir)
        if len(store) != manifest.num_chunks:
            return None
        return store, manifest
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        logger.warning("Ignoring unreadable persisted index in %s: %s", index_dir, exc)
        return None
