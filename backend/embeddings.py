"""Memory-conscious local embedding boundary backed by FastEmbed/ONNX."""

from collections.abc import Iterable, Sequence
from functools import lru_cache
import math
from typing import Protocol

from .config import (
    EMBEDDING_BATCH_SIZE,
    EMBEDDING_MODEL_NAME,
    EMBEDDING_THREADS,
    MIN_EMBEDDING_FREE_MB,
    MODEL_CACHE_DIR,
)
from .system_resources import available_memory_bytes


class EmbeddingUnavailableError(RuntimeError):
    """The local embedding model cannot be used safely right now."""


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


@lru_cache(maxsize=1)
def get_embedding_provider() -> FastEmbedProvider:
    return FastEmbedProvider()
