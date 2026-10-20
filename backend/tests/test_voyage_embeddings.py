"""Voyage transport and local spending-guard tests without real API calls."""

import json
import math

import httpx
import pytest

from backend.embeddings import (
    EmbeddingUnavailableError,
    FallbackEmbeddingProvider,
    VOYAGE_USAGE_PROVIDER_KEY,
    VoyageEmbeddingProvider,
)
from backend.resource_store import ResourceStore
from backend.tests.fake_embeddings import TinyEmbeddingProvider


def test_voyage_uses_retrieval_input_types_and_persists_usage(tmp_path):
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        vectors = []
        for index, _text in enumerate(payload["input"]):
            vector = [0.0] * 256
            vector[index % 256] = 2.0
            vectors.append({"index": index, "embedding": vector})
        return httpx.Response(200, json={"data": vectors, "usage": {"total_tokens": 3}})

    store = ResourceStore(tmp_path / "learnflow.db")
    provider = VoyageEmbeddingProvider(
        store,
        api_key="test-key",
        dimensions=256,
        batch_size=2,
        monthly_token_limit=1_000,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    document_vectors = provider.embed_documents(["alpha", "beta"])
    query_vector = provider.embed_query("question")

    assert requests[0]["model"] == "voyage-4-lite"
    assert requests[0]["input_type"] == "document"
    assert requests[0]["output_dimension"] == 256
    assert requests[1]["input_type"] == "query"
    assert len(document_vectors) == 2
    assert len(query_vector) == 256
    assert math.sqrt(sum(value * value for value in query_vector)) == pytest.approx(1.0)
    expected_units = len("alpha".encode()) + len("beta".encode()) + len(
        "question".encode()
    )
    assert store.current_monthly_usage(VOYAGE_USAGE_PROVIDER_KEY)[1] == expected_units


def test_voyage_limit_blocks_request_before_network_call(tmp_path):
    request_count = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(500)

    provider = VoyageEmbeddingProvider(
        ResourceStore(tmp_path / "learnflow.db"),
        api_key="test-key",
        monthly_token_limit=4,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(EmbeddingUnavailableError, match="monthly Voyage"):
        provider.embed_query("five!")
    assert request_count == 0


def test_local_embedding_fallback_is_explicit_and_sticky():
    class FailingVoyage:
        model_name = "voyage:test:4"

        def embed_documents(self, _texts):
            raise EmbeddingUnavailableError("unavailable")

        def embed_query(self, _text):
            raise AssertionError("primary must not be retried after fallback")

    provider = FallbackEmbeddingProvider(FailingVoyage(), TinyEmbeddingProvider())

    vectors = provider.embed_documents(["gradient descent"])

    assert provider.model_name == TinyEmbeddingProvider.model_name
    assert len(vectors[0]) == 4
    assert len(provider.embed_query("optimization")) == 4
