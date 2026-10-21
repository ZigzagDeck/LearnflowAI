"""Grounded, citation-bearing summaries over user-selected materials."""

from dataclasses import dataclass
from typing import Protocol

from .chat_service import AuthorizationError, SourceAuthorizer
from .chunking import NormalizedChunk
from .config import CHUNKING_PIPELINE_VERSION
from .contracts import Citation, SourceType, SummaryRequest, SummaryResponse
from .llm_provider import ProviderError
from .resource_store import ResourceStore, ResourceStoreError


MAX_SUMMARY_EVIDENCE_CHUNKS = 16


class SummaryUnavailableError(RuntimeError):
    """A summary dependency is unavailable."""


class SummaryAttemptError(ValueError):
    """The selected sources cannot produce a summary."""


class SummaryModelProvider(Protocol):
    async def generate_summary(self, evidence: list[str], style: str) -> str: ...


def _sample(chunks: list[NormalizedChunk], count: int) -> list[NormalizedChunk]:
    if count >= len(chunks):
        return chunks
    if count == 1:
        return [chunks[len(chunks) // 2]]
    return [
        chunks[round(index * (len(chunks) - 1) / (count - 1))]
        for index in range(count)
    ]


def _citation(chunk: NormalizedChunk) -> Citation:
    if chunk.source_type == SourceType.VIDEO.value:
        provenance: dict[str, int | float | None] = {
            "start_seconds": chunk.start_seconds,
            "end_seconds": chunk.end_seconds,
        }
    else:
        provenance = {chunk.reference_type: chunk.reference_number}
    return Citation(
        source_id=chunk.resource_id,
        source_type=SourceType(chunk.source_type),
        chunk_id=chunk.chunk_id,
        **provenance,
    )


def _select_evidence(store: ResourceStore, source_ids: list[str]) -> list[NormalizedChunk]:
    groups = [
        store.list_chunks(source_id, CHUNKING_PIPELINE_VERSION)
        for source_id in list(dict.fromkeys(source_ids))[:12]
    ]
    groups = [group for group in groups if group]
    if not groups:
        return []
    base, remainder = divmod(MAX_SUMMARY_EVIDENCE_CHUNKS, len(groups))
    selected: list[NormalizedChunk] = []
    for index, group in enumerate(groups):
        take = min(len(group), base + (1 if index < remainder else 0))
        selected.extend(_sample(group, max(1, take)))
    return selected[:MAX_SUMMARY_EVIDENCE_CHUNKS]


@dataclass
class GroundedSummaryService:
    authorizer: SourceAuthorizer
    provider: SummaryModelProvider
    store: ResourceStore

    async def generate(self, request: SummaryRequest, user_id: str) -> SummaryResponse:
        try:
            await self.authorizer.ensure_allowed(user_id, request.allowed_source_ids)
        except AuthorizationError:
            raise
        except Exception as exc:
            raise SummaryUnavailableError("Source authorization unavailable.") from exc
        try:
            evidence = _select_evidence(self.store, request.allowed_source_ids)
        except ResourceStoreError as exc:
            raise SummaryUnavailableError("Summary evidence is unavailable.") from exc
        if not evidence:
            raise SummaryAttemptError("The selected materials contain no summary-ready text.")
        try:
            summary = await self.provider.generate_summary(
                [chunk.text for chunk in evidence], request.style
            )
        except ProviderError as exc:
            raise SummaryUnavailableError("Summary generation is unavailable.") from exc
        if not summary.strip():
            raise SummaryUnavailableError("Summary generation returned no result.")
        return SummaryResponse(
            summary=summary.strip(),
            citations=[_citation(chunk) for chunk in evidence],
        )
