"""Local citation-safe retrieval adapters."""

from dataclasses import dataclass

from .config import CHUNKING_PIPELINE_VERSION
from .contracts import Citation, RetrievalHit, SourceType
from .embeddings import EmbeddingProvider, EmbeddingUnavailableError
from .resource_store import ChunkSearchHit, ResourceStore


def _to_retrieval_hit(match: ChunkSearchHit, score: float | None = None) -> RetrievalHit:
    chunk = match.chunk
    if chunk.source_type == SourceType.VIDEO.value:
        provenance = {
            "start_seconds": chunk.start_seconds,
            "end_seconds": chunk.end_seconds,
        }
    else:
        provenance = {chunk.reference_type: chunk.reference_number}
    return RetrievalHit(
        citation=Citation(
            source_id=chunk.resource_id,
            source_type=SourceType(chunk.source_type),
            chunk_id=chunk.chunk_id,
            **provenance,
        ),
        text=chunk.text,
        score=match.score if score is None else score,
    )


@dataclass(frozen=True)
class SQLiteLexicalRetriever:
    store: ResourceStore
    limit: int = 8

    async def retrieve_documents(
        self, question: str, allowed_source_ids: list[str]
    ) -> list[RetrievalHit]:
        matches = self.store.search_chunks(
            question,
            allowed_source_ids,
            CHUNKING_PIPELINE_VERSION,
            limit=self.limit,
        )
        hits: list[RetrievalHit] = []
        for match in matches:
            chunk = match.chunk
            if chunk.source_type == SourceType.VIDEO.value:
                continue
            hits.append(_to_retrieval_hit(match))
        return hits

    async def retrieve_video(
        self, question: str, video_source_id: str, playback_seconds: float
    ) -> list[RetrievalHit]:
        matches = self.store.search_chunks(
            question,
            [video_source_id],
            CHUNKING_PIPELINE_VERSION,
            limit=50,
        )
        return [
            _to_retrieval_hit(match)
            for match in matches
            if match.chunk.source_type == SourceType.VIDEO.value
            and match.chunk.end_seconds is not None
            and match.chunk.end_seconds <= playback_seconds
        ][: self.limit]


@dataclass(frozen=True)
class SQLiteHybridRetriever:
    """Fuse lexical and dense ranks without loading a vector database."""

    store: ResourceStore
    embedder: EmbeddingProvider
    limit: int = 8
    fusion_constant: int = 60

    async def retrieve_documents(
        self, question: str, allowed_source_ids: list[str]
    ) -> list[RetrievalHit]:
        candidate_limit = min(50, max(16, self.limit * 3))
        lexical = self.store.search_chunks(
            question,
            allowed_source_ids,
            CHUNKING_PIPELINE_VERSION,
            limit=candidate_limit,
        )
        try:
            query_vector = self.embedder.embed_query(question)
            dense = self.store.search_embeddings(
                query_vector,
                allowed_source_ids,
                CHUNKING_PIPELINE_VERSION,
                self.embedder.model_name,
                limit=candidate_limit,
            )
        except EmbeddingUnavailableError:
            dense = []

        matches: dict[str, ChunkSearchHit] = {}
        fused_scores: dict[str, float] = {}
        for ranked_results in (lexical, dense):
            for rank, match in enumerate(ranked_results, start=1):
                chunk_id = match.chunk.chunk_id
                matches[chunk_id] = match
                fused_scores[chunk_id] = fused_scores.get(chunk_id, 0.0) + (
                    1.0 / (self.fusion_constant + rank)
                )

        ranked_ids = sorted(
            fused_scores,
            key=lambda chunk_id: (-fused_scores[chunk_id], chunk_id),
        )
        hits: list[RetrievalHit] = []
        for chunk_id in ranked_ids:
            match = matches[chunk_id]
            if match.chunk.source_type == SourceType.VIDEO.value:
                continue
            hits.append(_to_retrieval_hit(match, fused_scores[chunk_id]))
            if len(hits) == self.limit:
                break
        return hits

    async def retrieve_video(
        self, question: str, video_source_id: str, playback_seconds: float
    ) -> list[RetrievalHit]:
        candidate_limit = 50
        lexical = self.store.search_chunks(
            question,
            [video_source_id],
            CHUNKING_PIPELINE_VERSION,
            limit=candidate_limit,
        )
        try:
            query_vector = self.embedder.embed_query(question)
            dense = self.store.search_embeddings(
                query_vector,
                [video_source_id],
                CHUNKING_PIPELINE_VERSION,
                self.embedder.model_name,
                limit=candidate_limit,
            )
        except EmbeddingUnavailableError:
            dense = []

        matches: dict[str, ChunkSearchHit] = {}
        scores: dict[str, float] = {}
        for results in (lexical, dense):
            for rank, match in enumerate(results, start=1):
                chunk = match.chunk
                if (
                    chunk.source_type != SourceType.VIDEO.value
                    or chunk.end_seconds is None
                    or chunk.end_seconds > playback_seconds
                ):
                    continue
                matches[chunk.chunk_id] = match
                scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + (
                    1.0 / (self.fusion_constant + rank)
                )
        ranked = sorted(scores, key=lambda item: (-scores[item], item))[: self.limit]
        return [_to_retrieval_hit(matches[item], scores[item]) for item in ranked]

