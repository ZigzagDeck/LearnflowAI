"""Guarded Voyage embeddings with an optional memory-conscious local fallback."""

from collections.abc import Iterable, Sequence
from functools import lru_cache
import math
from typing import Protocol

import httpx

from .config import (
    EMBEDDING_BATCH_SIZE,
    EMBEDDING_LOCAL_FALLBACK_ENABLED,
    EMBEDDING_MODEL_NAME,
    EMBEDDING_PROVIDER,
    EMBEDDING_THREADS,
    MIN_EMBEDDING_FREE_MB,
    MODEL_CACHE_DIR,
    VOYAGE_API_KEY,
    VOYAGE_EMBEDDING_BATCH_SIZE,
    VOYAGE_EMBEDDING_DIMENSIONS,
    VOYAGE_EMBEDDING_MODEL,
    VOYAGE_MONTHLY_TOKEN_LIMIT,
    DATABASE_PATH,
)
from .resource_store import (
    MonthlyUsageLimitError,
    ResourceStore,
    ResourceStoreError,
)
from .system_resources import available_memory_bytes


VOYAGE_EMBEDDING_ENDPOINT = "https://api.voyageai.com/v1/embeddings"
VOYAGE_USAGE_PROVIDER_KEY = "voyage_embedding_token_units"


class EmbeddingUnavailableError(RuntimeError):
    """The configured embedding provider cannot be used safely right now."""


class EmbeddingProvider(Protocol):
    model_name: str

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


def normalize_vector(values: Iterable[float]) -> list[float]:
    vector = [float(value) for value in values]
    magnitude = math.sqrt(sum(value * value for value in vector))
    if not vector or not math.isfinite(magnitude) or magnitude <= 0:
        raise EmbeddingUnavailableError("The embedding model returned an invalid vector.")
    normalized = [value / magnitude for value in vector]
    if not all(math.isfinite(value) for value in normalized):
        raise EmbeddingUnavailableError("The embedding model returned an invalid vector.")
    return normalized


class VoyageEmbeddingProvider:
    """Small REST adapter with conservative batching and a local usage ceiling."""

    def __init__(
        self,
        store: ResourceStore,
        *,
        api_key: str = VOYAGE_API_KEY,
        api_model: str = VOYAGE_EMBEDDING_MODEL,
        dimensions: int = VOYAGE_EMBEDDING_DIMENSIONS,
        batch_size: int = VOYAGE_EMBEDDING_BATCH_SIZE,
        monthly_token_limit: int = VOYAGE_MONTHLY_TOKEN_LIMIT,
        client: httpx.Client | None = None,
    ) -> None:
        if dimensions not in {256, 512, 1024, 2048}:
            raise ValueError("Voyage embedding dimensions must be 256, 512, 1024, or 2048.")
        self.store = store
        self.api_key = api_key
        self.api_model = api_model
        self.dimensions = dimensions
        self.batch_size = max(1, min(128, batch_size))
        self.monthly_token_limit = monthly_token_limit
        self.model_name = f"voyage:{api_model}:{dimensions}"
        self._client = client or httpx.Client(timeout=60.0)

    @staticmethod
    def _conservative_token_units(texts: Sequence[str]) -> int:
        # UTF-8 byte count intentionally overestimates normal text token usage.
        return max(1, sum(len(text.encode("utf-8")) for text in texts))

    def _embed(self, texts: Sequence[str], input_type: str) -> list[list[float]]:
        if not texts:
            return []
        if not self.api_key:
            raise EmbeddingUnavailableError(
                "Voyage embeddings require VOYAGE_API_KEY to be configured."
            )
        units = self._conservative_token_units(texts)
        try:
            self.store.reserve_monthly_usage(
                VOYAGE_USAGE_PROVIDER_KEY, units, self.monthly_token_limit
            )
            response = self._client.post(
                VOYAGE_EMBEDDING_ENDPOINT,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "input": list(texts),
                    "model": self.api_model,
                    "input_type": input_type,
                    "truncation": False,
                    "output_dimension": self.dimensions,
                    "output_dtype": "float",
                },
            )
            response.raise_for_status()
            payload = response.json()
        except MonthlyUsageLimitError as exc:
            raise EmbeddingUnavailableError(
                "The configured monthly Voyage embedding limit has been reached."
            ) from exc
        except ResourceStoreError as exc:
            raise EmbeddingUnavailableError(
                "Voyage usage tracking is unavailable; no request was sent."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise EmbeddingUnavailableError(
                "Voyage rejected the embedding request "
                f"with status {exc.response.status_code}."
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise EmbeddingUnavailableError(
                "Voyage could not process the embedding request."
            ) from exc

        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise EmbeddingUnavailableError("Voyage returned an invalid response.")
        ordered: list[list[float] | None] = [None] * len(texts)
        try:
            for position, item in enumerate(payload["data"]):
                if not isinstance(item, dict):
                    raise ValueError("Invalid embedding item.")
                index = int(item.get("index", position))
                if index < 0 or index >= len(ordered) or ordered[index] is not None:
                    raise ValueError("Invalid embedding index.")
                vector = normalize_vector(item["embedding"])
                if len(vector) != self.dimensions:
                    raise ValueError("Unexpected embedding dimensions.")
                ordered[index] = vector
        except (KeyError, TypeError, ValueError) as exc:
            raise EmbeddingUnavailableError("Voyage returned invalid embeddings.") from exc
        if any(vector is None for vector in ordered):
            raise EmbeddingUnavailableError("Voyage returned incomplete embeddings.")
        return [vector for vector in ordered if vector is not None]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            vectors.extend(
                self._embed(texts[start : start + self.batch_size], "document")
            )
        return vectors

    def embed_query(self, text: str) -> list[float]:
        vectors = self._embed([text], "query")
        if not vectors:
            raise EmbeddingUnavailableError("Voyage returned no query embedding.")
        return vectors[0]


class FastEmbedProvider:
    """Lazy CPU-only embedder with deliberately conservative memory settings."""

    def __init__(
        self,
        model_name: str = EMBEDDING_MODEL_NAME,
        *,
        batch_size: int = EMBEDDING_BATCH_SIZE,
        threads: int = EMBEDDING_THREADS,
        minimum_free_mb: int = MIN_EMBEDDING_FREE_MB,
    ):
        self.model_name = model_name
        self.batch_size = max(1, min(8, batch_size))
        self.threads = max(1, min(2, threads))
        self.minimum_free_bytes = max(256, minimum_free_mb) * 1024 * 1024
        self._model = None

    def _get_model(self):
        if self._model is not None:
            return self._model
        available = available_memory_bytes()
        if available is not None and available < self.minimum_free_bytes:
            available_mb = available // (1024 * 1024)
            required_mb = self.minimum_free_bytes // (1024 * 1024)
            raise EmbeddingUnavailableError(
                f"Semantic indexing needs at least {required_mb} MB free memory; "
                f"only {available_mb} MB is currently available."
            )
        try:
            from fastembed import TextEmbedding

            MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            self._model = TextEmbedding(
                model_name=self.model_name,
                cache_dir=str(MODEL_CACHE_DIR),
                threads=self.threads,
                providers=["CPUExecutionProvider"],
                lazy_load=True,
                enable_cpu_mem_arena=False,
            )
        except EmbeddingUnavailableError:
            raise
        except Exception as exc:
            raise EmbeddingUnavailableError(
                "The local semantic embedding model is unavailable."
            ) from exc
        return self._model

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            vectors = self._get_model().passage_embed(
                list(texts), batch_size=self.batch_size, parallel=None
            )
            return [normalize_vector(vector) for vector in vectors]
        except EmbeddingUnavailableError:
            raise
        except Exception as exc:
            raise EmbeddingUnavailableError(
                "Local semantic indexing could not embed this material."
            ) from exc

    def embed_query(self, text: str) -> list[float]:
        try:
            vectors = self._get_model().query_embed(
                [text], batch_size=1, parallel=None
            )
            return normalize_vector(next(iter(vectors)))
        except EmbeddingUnavailableError:
            raise
        except StopIteration:
            raise EmbeddingUnavailableError(
                "The local semantic embedding model returned no query vector."
            )
        except Exception as exc:
            raise EmbeddingUnavailableError(
                "Local semantic search could not embed this question."
            ) from exc


class FallbackEmbeddingProvider:
    """Switch permanently to local embeddings after the first Voyage failure."""

    def __init__(self, primary: EmbeddingProvider, fallback: EmbeddingProvider):
        self.primary = primary
        self.fallback = fallback
        self._active = primary

    @property
    def model_name(self) -> str:
        return self._active.model_name

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        try:
            return self._active.embed_documents(texts)
        except EmbeddingUnavailableError:
            if self._active is self.fallback:
                raise
            self._active = self.fallback
            return self._active.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        try:
            return self._active.embed_query(text)
        except EmbeddingUnavailableError:
            if self._active is self.fallback:
                raise
            self._active = self.fallback
            return self._active.embed_query(text)


@lru_cache(maxsize=1)
def get_embedding_provider() -> EmbeddingProvider:
    if EMBEDDING_PROVIDER == "fastembed":
        return FastEmbedProvider()
    if EMBEDDING_PROVIDER != "voyage":
        raise EmbeddingUnavailableError(
            "LEARNFLOW_EMBEDDING_PROVIDER must be voyage or fastembed."
        )
    primary = VoyageEmbeddingProvider(ResourceStore(DATABASE_PATH))
    if EMBEDDING_LOCAL_FALLBACK_ENABLED:
        return FallbackEmbeddingProvider(primary, FastEmbedProvider())
    return primary
