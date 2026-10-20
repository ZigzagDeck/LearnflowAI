"""Embedding safety boundary tests that never load or download a real model."""

import math

import pytest

import backend.embeddings as embeddings


def test_vectors_are_normalized_for_cosine_search():
    vector = embeddings.normalize_vector([3.0, 4.0])

    assert vector == pytest.approx([0.6, 0.8])
    assert math.sqrt(sum(value * value for value in vector)) == pytest.approx(1.0)


def test_model_load_is_blocked_before_import_when_free_memory_is_low(monkeypatch):
    monkeypatch.setattr(embeddings, "available_memory_bytes", lambda: 100 * 1024 * 1024)
    provider = embeddings.FastEmbedProvider(minimum_free_mb=768)

    with pytest.raises(embeddings.EmbeddingUnavailableError, match="768 MB"):
        provider.embed_query("safe test")
