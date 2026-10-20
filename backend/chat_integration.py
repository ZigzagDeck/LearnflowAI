"""Opt-in single-user local wiring for grounded retrieval and Bedrock chat."""

from dataclasses import dataclass

from .chat_service import AuthorizationError, GroundedChatService
from .config import (
    BEDROCK_MAX_OUTPUT_TOKENS,
    BEDROCK_MODEL_ID,
    BEDROCK_MONTHLY_TOKEN_UNIT_LIMIT,
    BEDROCK_REGION,
)
from .embeddings import get_embedding_provider
from .llm_provider import BedrockConfig, BedrockConverseProvider
from .resource_store import ResourceStore
from .retrieval import SQLiteHybridRetriever


@dataclass(frozen=True)
class LocalResourceAuthorizer:
    """Permit only ready resources in this installation's private SQLite store."""

    store: ResourceStore

    async def ensure_allowed(self, session_id: str, source_ids: list[str]) -> None:
        del session_id  # Sessions are UI state until real authentication is added.
        for source_id in dict.fromkeys(source_ids):
            resource = self.store.get_by_resource_id(source_id)
            if resource is None or resource.status != "ready":
                raise AuthorizationError("Requested source is unavailable.")


def build_local_bedrock_chat_service(store: ResourceStore) -> GroundedChatService:
    """Build the explicit local/single-user chat integration without making a call."""
    provider = BedrockConverseProvider(
        BedrockConfig(
            region=BEDROCK_REGION,
            model_id=BEDROCK_MODEL_ID,
            max_tokens=BEDROCK_MAX_OUTPUT_TOKENS,
            monthly_token_unit_limit=BEDROCK_MONTHLY_TOKEN_UNIT_LIMIT,
        ),
        store,
    )
    return GroundedChatService(
        authorizer=LocalResourceAuthorizer(store),
        retriever=SQLiteHybridRetriever(store, get_embedding_provider()),
        provider=provider,
    )
