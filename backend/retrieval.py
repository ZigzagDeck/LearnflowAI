"""Local citation-safe retrieval adapters."""

from dataclasses import dataclass

from .config import CHUNKING_PIPELINE_VERSION
from .contracts import Citation, RetrievalHit, SourceType
from .resource_store import ResourceStore


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
            provenance = {chunk.reference_type: chunk.reference_number}
            hits.append(
                RetrievalHit(
                    citation=Citation(
                        source_id=chunk.resource_id,
                        source_type=SourceType(chunk.source_type),
                        chunk_id=chunk.chunk_id,
                        **provenance,
                    ),
                    text=chunk.text,
                    score=match.score,
                )
            )
        return hits

    async def retrieve_video(
        self, question: str, video_source_id: str, playback_seconds: float
    ) -> list[RetrievalHit]:
        # Timestamped transcript chunks arrive in the dedicated video milestone.
        return []

