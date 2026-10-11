from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import FALLBACK_MESSAGE
from app.domain import Generation
from app.inference.generators import GenerationError
from app.main import create_app
from app.service import ServiceInfo

from .conftest import StubGenerator

INFO = ServiceInfo(
    documents=("sample.md",),
    chunks=4,
    embedding_model="hashing:512",
    llm_provider="stub",
    llm_model=None,
    similarity_threshold=0.2,
    top_k=3,
)


class FailingGenerator:
    name = "failing"

    def generate(self, question, passages):
        raise GenerationError("LLM authentication failed: check ANTHROPIC_API_KEY")


@pytest.fixture
def client_for(make_pipeline):
    clients: list[TestClient] = []

    def _client(generator=None, **kwargs) -> TestClient:
        app = create_app(pipeline=make_pipeline(generator, **kwargs), service_info=INFO)
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client

    yield _client
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(client_for) -> Iterator[TestClient]:
    yield client_for(StubGenerator(Generation(True, "Backups are retained for 30 calendar days.", ("chunk_01",), 164)))


def test_query_returns_contract_shape(client: TestClient) -> None:
    response = client.post("/api/query", json={"question": "How long are database backups retained?"})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"answer", "sources", "tokens_used"}
    assert body["answer"] == "Backups are retained for 30 calendar days."
    assert body["tokens_used"] == 164
    assert len(body["sources"]) == 1
    source = body["sources"][0]
    assert set(source) == {"chunk_id", "similarity_score", "text_snippet"}
    assert source["chunk_id"] == "chunk_01"
    assert 0 < source["similarity_score"] <= 1
    assert source["similarity_score"] == round(source["similarity_score"], 2)
    assert response.headers["X-DocuSense-Outcome"] == "answered"


def test_out_of_scope_question_returns_exact_fallback(client_for) -> None:
    client = client_for(StubGenerator(), threshold=0.99)
    response = client.post("/api/query", json={"question": "Who won the FIFA World Cup in 2018?"})

    assert response.status_code == 200
    assert response.json() == {"answer": FALLBACK_MESSAGE, "sources": [], "tokens_used": 0}
    assert response.headers["X-DocuSense-Outcome"] == "fallback"
    assert response.headers["X-DocuSense-Reason"] == "low_similarity"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"question": ""},
        {"question": "   "},
        {"question": 42},
        {"question": "x" * 1001},
        {"question": "valid?", "top_k": 50},
    ],
)
def test_invalid_requests_are_rejected_with_422(client: TestClient, payload: dict) -> None:
    assert client.post("/api/query", json=payload).status_code == 422


def test_llm_failure_maps_to_502(client_for) -> None:
    client = client_for(FailingGenerator())
    response = client.post("/api/query", json={"question": "How long are database backups retained?"})
    assert response.status_code == 502
    assert "ANTHROPIC_API_KEY" in response.json()["detail"]


def test_health_reports_index_information(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "documents": ["sample.md"],
        "chunks": 4,
        "embedding_model": "hashing:512",
        "llm_provider": "stub",
        "llm_model": None,
        "similarity_threshold": 0.2,
        "top_k": 3,
    }


def test_openapi_documents_the_query_endpoint(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/api/query" in spec["paths"]
    assert "/api/health" in spec["paths"]
