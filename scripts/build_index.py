"""Build (or verify) the persisted vector index.

Usage:
    python -m scripts.build_index           # reuse the index if it is up to date
    python -m scripts.build_index --force   # always rebuild

The Docker image runs this at build time so the container starts instantly and offline.
"""

from __future__ import annotations

import argparse
import logging

from app.config import get_settings
from app.indexing.embeddings import create_embedder
from app.indexing.index_builder import load_or_build_index
from app.ingestion.chunker import MarkdownChunker


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="rebuild even if the persisted index is current")
    args = parser.parse_args()

    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper(), format="%(levelname)s %(name)s: %(message)s")

    embedder = create_embedder(settings)
    chunker = MarkdownChunker(settings.chunk_size, settings.chunk_overlap)
    store, manifest = load_or_build_index(
        settings.document_path, settings.index_dir, chunker, embedder, force_rebuild=args.force
    )

    print(f"documents      : {', '.join(manifest.documents)}")
    print(f"chunks         : {len(store)}  (size={manifest.chunk_size}, overlap={manifest.chunk_overlap})")
    print(f"embedding model: {manifest.embedding_model}  (dim={manifest.dimension})")
    print(f"index dir      : {settings.index_dir.resolve()}")


if __name__ == "__main__":
    main()
