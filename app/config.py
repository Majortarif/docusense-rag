"""Runtime configuration, loaded from environment variables (and an optional `.env` file)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: The exact response returned whenever an answer cannot be grounded in the document.
FALLBACK_MESSAGE = "The provided documentation does not contain sufficient information to answer this question."

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class Settings(BaseSettings):
    """All tunables of the service. Every field maps to an upper-case environment variable."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Ingestion -------------------------------------------------------------------------
    document_path: Path = Path("data/policies.md")
    index_dir: Path = Path(".index")
    chunk_size: int = Field(default=800, ge=100, le=4000, description="Max characters per chunk.")
    chunk_overlap: int = Field(default=120, ge=0, description="Max characters shared by neighbours.")

    # --- Embeddings ------------------------------------------------------------------------
    embedding_provider: Literal["fastembed", "hashing"] = "fastembed"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_cache_dir: Path = Path(".cache/fastembed")

    # --- Retrieval -------------------------------------------------------------------------
    top_k: int = Field(default=4, ge=1, le=20)
    similarity_threshold: float = Field(default=0.65, ge=-1.0, le=1.0)
    max_context_tokens: int = Field(default=1500, ge=100)

    # --- Generation ------------------------------------------------------------------------
    llm_provider: Literal["anthropic", "extractive"] = "anthropic"
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: Effort = "low"
    anthropic_max_tokens: int = Field(default=2048, ge=256)
    anthropic_fallbacks: bool = True
    llm_timeout_seconds: float = Field(default=60.0, gt=0)

    # --- Guardrails ------------------------------------------------------------------------
    block_prompt_injection: bool = True

    # --- Operations ------------------------------------------------------------------------
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _overlap_smaller_than_chunk(self) -> Settings:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings (cached after the first call)."""
    return Settings()
