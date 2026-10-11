"""Request/response contracts of the public API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_QUESTION_CHARS = 1000


class QueryRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"question": "What is the policy on database backup retention periods?"}]},
    )

    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)

    @field_validator("question")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must not be blank")
        return value.strip()


class Source(BaseModel):
    chunk_id: str
    similarity_score: float = Field(description="Cosine similarity between the question and the chunk.")
    text_snippet: str


class QueryResponse(BaseModel):
    answer: str
    sources: list[Source]
    tokens_used: int = Field(description="LLM input + output tokens spent on this query (0 if no LLM call).")


class HealthResponse(BaseModel):
    status: str
    documents: list[str]
    chunks: int
    embedding_model: str
    llm_provider: str
    llm_model: str | None
    similarity_threshold: float
    top_k: int


class ErrorResponse(BaseModel):
    detail: str
