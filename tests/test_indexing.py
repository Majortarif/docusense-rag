from __future__ import annotations

import json

import numpy as np
import pytest

from app.domain import Chunk, Document
from app.indexing.embeddings import HashingEmbedder, l2_normalize
from app.indexing.index_builder import MANIFEST_FILE, load_or_build_index
from app.indexing.vector_store import FaissVectorStore
from app.ingestion.chunker import MarkdownChunker

from .conftest import SAMPLE_MARKDOWN


def _chunk(i: int) -> Chunk:
    return Chunk(chunk_id=f"chunk_{i:02d}", text=f"text {i}", section="s", source="d.md")


def test_hashing_embedder_is_deterministic_and_normalised(embedder: HashingEmbedder) -> None:
    a = embedder.embed_documents(["database backups are retained", "passwords are long"])
    b = embedder.embed_documents(["database backups are retained", "passwords are long"])
    np.testing.assert_array_equal(a, b)
    np.testing.assert_allclose(np.linalg.norm(a, axis=1), 1.0, rtol=1e-5)


def test_hashing_embedder_ranks_lexical_overlap_higher(embedder: HashingEmbedder) -> None:
    query = embedder.embed_query("backup retention period")
    docs = embedder.embed_documents(["backup retention is 30 days", "office plants need water"])
    scores = docs @ query
    assert scores[0] > scores[1]


def test_l2_normalize_leaves_zero_vectors_alone() -> None:
    out = l2_normalize(np.zeros((2, 3)))
    assert not np.isnan(out).any()


def test_vector_store_returns_best_matches_in_order() -> None:
    store = FaissVectorStore(dimension=2)
    vectors = l2_normalize(np.array([[1.0, 0.0], [0.0, 1.0], [0.7, 0.7]]))
    store.add([_chunk(0), _chunk(1), _chunk(2)], vectors)

    hits = store.search(np.array([1.0, 0.0]), k=2)
    assert [h.chunk.chunk_id for h in hits] == ["chunk_00", "chunk_02"]
    assert hits[0].score == pytest.approx(1.0)
    assert hits[0].score >= hits[1].score


def test_vector_store_handles_k_larger_than_index_and_empty_index() -> None:
    assert FaissVectorStore(dimension=2).search(np.array([1.0, 0.0]), k=5) == []
    store = FaissVectorStore(dimension=2)
    store.add([_chunk(0)], l2_normalize(np.array([[1.0, 1.0]])))
    assert len(store.search(np.array([1.0, 0.0]), k=10)) == 1


def test_vector_store_rejects_mismatched_shapes() -> None:
    store = FaissVectorStore(dimension=3)
    with pytest.raises(ValueError):
        store.add([_chunk(0)], np.ones((2, 3)))
    with pytest.raises(ValueError):
        store.add([_chunk(0)], np.ones((1, 4)))
    with pytest.raises(ValueError):
        store.search(np.ones(4), k=1)


def test_vector_store_round_trips_to_disk(tmp_path) -> None:
    store = FaissVectorStore(dimension=2)
    store.add([_chunk(0), _chunk(1)], l2_normalize(np.array([[1.0, 0.0], [0.0, 1.0]])))
    store.save(tmp_path)

    loaded = FaissVectorStore.load(tmp_path)
    assert loaded.chunks == store.chunks
    assert [h.chunk.chunk_id for h in loaded.search(np.array([0.0, 1.0]), k=1)] == ["chunk_01"]


def test_index_is_reused_until_documents_or_config_change(tmp_path, embedder: HashingEmbedder) -> None:
    doc_path = tmp_path / "policies.md"
    doc_path.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    index_dir = tmp_path / "index"
    chunker = MarkdownChunker(800, 120)

    _, first = load_or_build_index(doc_path, index_dir, chunker, embedder)
    built_at = (index_dir / MANIFEST_FILE).stat().st_mtime_ns

    _, second = load_or_build_index(doc_path, index_dir, chunker, embedder)
    assert second == first
    assert (index_dir / MANIFEST_FILE).stat().st_mtime_ns == built_at, "unchanged inputs must reuse the index"

    doc_path.write_text(SAMPLE_MARKDOWN + "\n## 3. New\n\nA brand new rule.\n", encoding="utf-8")
    store, third = load_or_build_index(doc_path, index_dir, chunker, embedder)
    assert third.documents_sha256 != first.documents_sha256
    assert third.num_chunks == first.num_chunks + 1 == len(store)

    _, fourth = load_or_build_index(doc_path, index_dir, MarkdownChunker(400, 60), embedder)
    assert (fourth.chunk_size, fourth.chunk_overlap) == (400, 60)


def test_corrupt_persisted_index_is_rebuilt(tmp_path, embedder: HashingEmbedder) -> None:
    doc_path = tmp_path / "policies.md"
    doc_path.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    index_dir = tmp_path / "index"
    chunker = MarkdownChunker(800, 120)
    load_or_build_index(doc_path, index_dir, chunker, embedder)

    (index_dir / "chunks.json").write_text(json.dumps([]), encoding="utf-8")
    store, _ = load_or_build_index(doc_path, index_dir, chunker, embedder)
    assert len(store) == len(chunker.chunk_documents([Document(name="policies.md", text=SAMPLE_MARKDOWN)]))
