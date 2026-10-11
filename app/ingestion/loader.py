"""Load markdown / plain-text documents from a file or a directory."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

from app.domain import Document

SUPPORTED_SUFFIXES = frozenset({".md", ".markdown", ".txt"})


def load_documents(path: Path) -> list[Document]:
    """Load one document, or every supported document in a directory (sorted by name).

    Raises:
        FileNotFoundError: if ``path`` does not exist.
        ValueError: if no supported, non-empty document is found.
    """
    if not path.exists():
        raise FileNotFoundError(f"Document path does not exist: {path}")

    if path.is_dir():
        files = sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES)
    elif path.suffix.lower() in SUPPORTED_SUFFIXES:
        files = [path]
    else:
        raise ValueError(f"Unsupported document type '{path.suffix}'. Use one of {sorted(SUPPORTED_SUFFIXES)}")

    documents = [Document(name=f.name, text=_read_text(f)) for f in files]
    documents = [doc for doc in documents if doc.text.strip()]
    if not documents:
        raise ValueError(f"No non-empty .md/.txt documents found at {path}")
    return documents


def fingerprint(documents: Sequence[Document]) -> str:
    """Stable SHA-256 over document names and contents; used to detect when re-indexing is needed."""
    digest = hashlib.sha256()
    for doc in documents:
        digest.update(doc.name.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(doc.text.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def _read_text(path: Path) -> str:
    # utf-8-sig drops a BOM if present; newlines are normalised so chunking is platform-independent.
    text = path.read_text(encoding="utf-8-sig")
    return text.replace("\r\n", "\n").replace("\r", "\n")
