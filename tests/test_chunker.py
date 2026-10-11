from __future__ import annotations

import pytest

from app.domain import Document
from app.ingestion.chunker import MarkdownChunker
from app.ingestion.loader import fingerprint, load_documents

from .conftest import POLICY_DOCUMENT, SAMPLE_MARKDOWN

LONG_SECTION = "## Long\n\n" + " ".join(f"Sentence number {i} explains one rule of the policy." for i in range(60))


def test_chunking_is_deterministic(sample_document: Document) -> None:
    first = MarkdownChunker(200, 40).chunk_documents([sample_document])
    second = MarkdownChunker(200, 40).chunk_documents([sample_document])
    assert first == second


def test_chunk_ids_are_sequential_and_zero_padded(sample_document: Document) -> None:
    chunks = MarkdownChunker(800, 120).chunk_documents([sample_document])
    assert [c.chunk_id for c in chunks] == [f"chunk_{i:02d}" for i in range(len(chunks))]


def test_chunk_id_width_grows_with_chunk_count() -> None:
    text = "\n\n".join(f"## Section {i}\n\nRule {i}." for i in range(120))
    chunks = MarkdownChunker(100, 0).chunk_documents([Document(name="many.md", text=text)])
    assert len(chunks) > 100
    assert chunks[0].chunk_id == "chunk_000"


def test_sections_carry_heading_breadcrumbs_without_document_title(sample_document: Document) -> None:
    chunks = MarkdownChunker(800, 120).chunk_documents([sample_document])
    sections = [c.section for c in chunks]
    assert sections == ["Sample Handbook", "1. Backups > 1.1 Retention", "1. Backups > 1.2 Encryption", "2. Passwords"]
    assert chunks[1].embedding_text.startswith("1. Backups > 1.1 Retention\n\n")


def test_multiple_level_one_headings_stay_in_breadcrumbs() -> None:
    doc = Document(name="d.md", text="# Part A\n\n## Topic\n\nBody a.\n\n# Part B\n\nBody b.")
    sections = [section for section, _ in MarkdownChunker().split_sections(doc.text)]
    assert sections == ["Part A > Topic", "Part B"]


def test_headings_inside_code_fences_are_ignored() -> None:
    text = "## Real\n\n```\n# not a heading\n```\n\nAfter the fence."
    sections = MarkdownChunker().split_sections(text)
    assert len(sections) == 1
    assert sections[0][0] == "Real"
    assert "# not a heading" in sections[0][1]


def test_chunks_respect_size_limit_and_overlap() -> None:
    chunker = MarkdownChunker(chunk_size=300, chunk_overlap=80)
    chunks = chunker.chunk_documents([Document(name="long.md", text=LONG_SECTION)])
    assert len(chunks) > 3
    assert all(len(c.text) <= 300 for c in chunks)
    for previous, current in zip(chunks, chunks[1:], strict=False):
        last_sentence = previous.text.rsplit(". ", 1)[-1]
        assert current.text.startswith(last_sentence), "next chunk must start with the previous chunk's tail"


def test_zero_overlap_produces_disjoint_chunks() -> None:
    doc = Document(name="l.md", text=LONG_SECTION)
    chunks = MarkdownChunker(chunk_size=300, chunk_overlap=0).chunk_documents([doc])
    joined = " ".join(c.text for c in chunks)
    assert joined.count("Sentence number 10 ") == 1


def test_overlap_never_crosses_sections() -> None:
    text = "## A\n\nAlpha rule one. Alpha rule two.\n\n## B\n\nBeta rule one."
    chunks = MarkdownChunker(chunk_size=200, chunk_overlap=100).chunk_documents([Document(name="x.md", text=text)])
    assert [c.text for c in chunks] == ["Alpha rule one. Alpha rule two.", "Beta rule one."]


def test_unbreakable_text_is_hard_split() -> None:
    chunks = MarkdownChunker(chunk_size=100, chunk_overlap=0).split_text("x" * 250)
    assert [len(c) for c in chunks] == [100, 100, 50]


def test_plain_text_without_headings_is_one_section() -> None:
    chunks = MarkdownChunker().chunk_documents([Document(name="a.txt", text="Just some policy text.")])
    assert len(chunks) == 1
    assert chunks[0].section == ""


@pytest.mark.parametrize(("size", "overlap"), [(0, 0), (100, 100), (100, 150), (100, -1)])
def test_invalid_parameters_are_rejected(size: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        MarkdownChunker(size, overlap)


def test_loader_reads_policy_document_and_fingerprints_it() -> None:
    docs = load_documents(POLICY_DOCUMENT)
    assert [d.name for d in docs] == ["policies.md"]
    assert "\r" not in docs[0].text
    assert fingerprint(docs) == fingerprint(load_documents(POLICY_DOCUMENT))


def test_loader_handles_directories_and_bad_paths(tmp_path) -> None:
    (tmp_path / "b.md").write_text("B text", encoding="utf-8")
    (tmp_path / "a.txt").write_text("A text", encoding="utf-8")
    (tmp_path / "ignored.pdf").write_bytes(b"%PDF")
    assert [d.name for d in load_documents(tmp_path)] == ["a.txt", "b.md"]

    with pytest.raises(FileNotFoundError):
        load_documents(tmp_path / "missing.md")
    with pytest.raises(ValueError):
        load_documents(tmp_path / "ignored.pdf")


def test_fingerprint_changes_with_content() -> None:
    a = fingerprint([Document(name="d.md", text=SAMPLE_MARKDOWN)])
    b = fingerprint([Document(name="d.md", text=SAMPLE_MARKDOWN + "\nNew rule.")])
    assert a != b
