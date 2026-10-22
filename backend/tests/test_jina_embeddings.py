"""Jina transport, retry, fallback, and local spending-guard tests."""

import json
import math

import httpx
import pytest

from backend.embeddings import (
    EmbeddingUnavailableError,
    FallbackEmbeddingProvider,
    JINA_USAGE_PROVIDER_KEY,
    JinaEmbeddingProvider,
    normalize_vector,
)
from backend.resource_store import ResourceStore
from backend.tests.fake_embeddings import TinyEmbeddingProvider


def _success_response(payload: dict[str, object]) -> httpx.Response:
    vectors = []
    for index, _text in enumerate(payload["input"]):
        vector = [0.0] * 256
        vector[index % 256] = 2.0
        vectors.append({"index": index, "embedding": vector})
    return httpx.Response(200, json={"data": vectors, "usage": {"total_tokens": 3}})


def test_jina_uses_retrieval_tasks_and_persists_usage(tmp_path):
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        return _success_response(payload)

    store = ResourceStore(tmp_path / "learnflow.db")
    provider = JinaEmbeddingProvider(
        store,
        api_key="test-key",
        dimensions=256,
        batch_size=2,
        monthly_token_limit=1_000,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        retry_delays=(),
    )

    document_vectors = provider.embed_documents(["alpha", "beta"])
    query_vector = provider.embed_query("question")

    assert requests[0]["model"] == "jina-embeddings-v3"
    assert requests[0]["task"] == "retrieval.passage"
    assert requests[0]["dimensions"] == 256
    assert requests[0]["normalized"] is True
    assert requests[1]["task"] == "retrieval.query"
    assert len(document_vectors) == 2
    assert len(query_vector) == 256
    assert math.sqrt(sum(value * value for value in query_vector)) == pytest.approx(1.0)
    expected_units = len("alpha".encode()) + len("beta".encode()) + len(
        "question".encode()
    )
    assert store.current_monthly_usage(JINA_USAGE_PROVIDER_KEY)[1] == expected_units


def test_jina_retries_429_and_uses_retry_after(tmp_path):
    request_count = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "3"},
                json={"code": "RATE_TOKEN_LIMIT_EXCEEDED", "detail": "Slow down"},
            )
        return _success_response(json.loads(request.content))

    provider = JinaEmbeddingProvider(
        ResourceStore(tmp_path / "learnflow.db"),
        api_key="test-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        retry_delays=(1,),
        sleep=delays.append,
    )

    assert len(provider.embed_query("question")) == 256
    assert request_count == 2
    assert delays == [3.0]


def test_jina_final_error_keeps_safe_detail_and_request_id(tmp_path):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"x-request-id": "request-123"},
            json={"code": "RATE_LIMIT", "detail": "Free-key token limit reached"},
        )

    provider = JinaEmbeddingProvider(
        ResourceStore(tmp_path / "learnflow.db"),
        api_key="test-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        retry_delays=(),
    )

    with pytest.raises(EmbeddingUnavailableError) as error:
        provider.embed_query("question")
    assert "Free-key token limit reached" in str(error.value)
    assert "request-123" in str(error.value)


def test_jina_limit_blocks_request_before_network_call(tmp_path):
    request_count = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(500)

    provider = JinaEmbeddingProvider(
        ResourceStore(tmp_path / "learnflow.db"),
        api_key="test-key",
        monthly_token_limit=4,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(EmbeddingUnavailableError, match="monthly Jina"):
        provider.embed_query("five!")
    assert request_count == 0


def test_local_embedding_fallback_is_explicit_and_sticky():
    class FailingJina:
        model_name = "jina:test:4"

        def embed_documents(self, _texts):
            raise EmbeddingUnavailableError("unavailable")

        def embed_query(self, _text):
            raise AssertionError("primary must not be retried after fallback")

    provider = FallbackEmbeddingProvider(FailingJina(), TinyEmbeddingProvider())

    vectors = provider.embed_documents(["gradient descent"])

    assert provider.model_name == TinyEmbeddingProvider.model_name
    assert len(vectors[0]) == 4
    assert len(provider.embed_query("optimization")) == 4


def test_vectors_are_normalized_for_cosine_search():
    vector = normalize_vector([3.0, 4.0])

    assert vector == pytest.approx([0.6, 0.8])
    assert math.sqrt(sum(value * value for value in vector)) == pytest.approx(1.0)
