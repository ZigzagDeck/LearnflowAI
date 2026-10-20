"""Tiny deterministic embeddings used to keep tests model- and RAM-independent."""

from collections.abc import Sequence
import math
import re


class TinyEmbeddingProvider:
    model_name = "test-tiny-v1"

    _concepts = (
        {"gradient", "descent", "optimization", "optimisation"},
        {"neural", "network", "backpropagation", "weights", "training"},
        {"photosynthesis", "light", "plant", "energy"},
        {"ocean", "marine", "sea", "water"},
    )

    @classmethod
    def _embed(cls, text: str) -> list[float]:
        terms = set(re.findall(r"[^\W_]+", text.casefold()))
        vector = [float(len(terms & concept)) for concept in cls._concepts]
        if not any(vector):
            vector[-1] = 0.01
        magnitude = math.sqrt(sum(value * value for value in vector))
        return [value / magnitude for value in vector]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)
