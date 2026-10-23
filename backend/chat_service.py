"""Grounded Q&A coordinator with fail-closed source and playback safeguards.

This module does not provide source authorization or retrieval; those trusted
integrations must be supplied by the application at startup.
"""
from dataclasses import dataclass
from typing import Protocol

from .contracts import ChatRequest, ChatResponse, RetrievalHit, SourceType
from .llm_provider import ModelProvider, ProviderError


class AuthorizationError(PermissionError):
    """Requested learning sources are not accessible to the verified learner."""


class ChatUnavailableError(RuntimeError):
    """Required AI or retrieval dependency is not currently available."""


class SourceAuthorizer(Protocol):
    async def ensure_allowed(self, user_id: str, source_ids: list[str]) -> None:
        """Check trusted authenticated ownership/session association."""


class EvidenceRetriever(Protocol):
    async def retrieve_documents(
        self, question: str, allowed_source_ids: list[str]
    ) -> list[RetrievalHit]: ...

    async def retrieve_video(
        self, question: str, video_source_id: str, playback_seconds: float
    ) -> list[RetrievalHit]: ...


class ConversationHistory(Protocol):
    def get_recent_chat_turns(
        self,
        session_id: str,
        owner_user_id: str,
        *,
        limit: int = 8,
        source_ids: list[str] | None = None,
        video_scopes: dict[str, float] | None = None,
    ) -> list[dict[str, str]]: ...

REFUSAL = "I cannot answer that from the material available at your current lesson position."


@dataclass
class GroundedChatService:
    authorizer: SourceAuthorizer
    retriever: EvidenceRetriever
    provider: ModelProvider
    history: ConversationHistory | None = None

    async def answer(
        self, request: ChatRequest, user_id: str | None = None
    ) -> ChatResponse:
        # Session IDs/allowed-source IDs supplied by a client are not proof of ownership.
        try:
            await self.authorizer.ensure_allowed(
                user_id or request.session_id, request.allowed_source_ids
            )
        except AuthorizationError:
            raise
        except Exception as exc:
            raise ChatUnavailableError("Source authorization unavailable.") from exc

        conversation: list[dict[str, str]] = []
        playback_limits = {
            scope.source_id: scope.playback_seconds for scope in request.video_scopes
        }
        if request.video_source_id is not None and request.playback_seconds is not None:
            playback_limits[request.video_source_id] = request.playback_seconds
        if self.history is not None and user_id is not None:
            try:
                conversation = self.history.get_recent_chat_turns(
                    request.session_id,
                    user_id,
                    limit=8,
                    source_ids=request.allowed_source_ids,
                    video_scopes=playback_limits,
                )
            except Exception as exc:
                raise ChatUnavailableError("Conversation history unavailable.") from exc
        retrieval_query = request.question
        if conversation:
            recent_context = " ".join(
                turn["content"][:600] for turn in conversation[-2:]
            )
            retrieval_query = f"{recent_context}\nFollow-up question: {request.question}"

        try:
            documents = await self.retriever.retrieve_documents(
                retrieval_query, request.allowed_source_ids
            )
            video_groups: list[list[RetrievalHit]] = []
            if request.video_source_id is not None:
                # ChatRequest guarantees playback_seconds exists with video_source_id.
                video_groups.append(
                    await self.retriever.retrieve_video(
                        retrieval_query,
                        request.video_source_id,
                        request.playback_seconds,
                    )
                )
            for scope in request.video_scopes:
                video_groups.append(
                    await self.retriever.retrieve_video(
                        retrieval_query,
                        scope.source_id,
                        scope.playback_seconds,
                    )
                )
            evidence_groups = [
                (documents, "document"),
                *[(group, "video") for group in video_groups],
            ]
            ranked_hits = [
                (group[position], channel)
                for position in range(max((len(group) for group, _ in evidence_groups), default=0))
                for group, channel in evidence_groups
                if position < len(group)
            ]
        except Exception as exc:
            raise ChatUnavailableError("Evidence retrieval unavailable.") from exc

        allowed = set(request.allowed_source_ids)
        evidence = []
        seen = set()
        # Never accept a video hit returned through the document interface, or vice versa.
        for hit, channel in ranked_hits:
            citation = hit.citation
            if citation.source_id not in allowed:
                continue
            if channel == "document":
                if citation.source_type not in (
                    SourceType.PDF, SourceType.PPTX, SourceType.IMAGE
                ):
                    continue
            else:
                cutoff = playback_limits.get(citation.source_id)
                if (
                    citation.source_type != SourceType.VIDEO
                    or citation.end_seconds is None
                    or cutoff is None
                    or citation.end_seconds > cutoff
                ):
                    # Exclude full chunks overlapping the current playback cutoff.
                    continue

            key = (citation.source_id, citation.chunk_id)
            if key not in seen:
                seen.add(key)
                evidence.append(hit)
            if len(evidence) >= 8:
                break

        if not evidence:
            return ChatResponse(
                session_id=request.session_id,
                answer=REFUSAL,
                grounded=False,
                citations=[],
            )

        try:
            evidence_text = [hit.text for hit in evidence]
            answer = (
                await self.provider.answer(request.question, evidence_text, conversation)
                if conversation
                else await self.provider.answer(request.question, evidence_text)
            )
        except ProviderError as exc:
            raise ChatUnavailableError("Answer generation unavailable.") from exc
        except Exception as exc:
            raise ChatUnavailableError("Answer generation unavailable.") from exc

        if not isinstance(answer, str) or not answer.strip():
            raise ChatUnavailableError("Answer generation returned no result.")

        # These are candidate evidence citations, NOT LLM-generated citations
        # and NOT an automated entailment verification of answer accuracy.
        return ChatResponse(
            session_id=request.session_id,
            answer=answer.strip(),
            grounded=True,
            citations=[hit.citation for hit in evidence],
        )
