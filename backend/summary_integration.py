"""Local wiring for grounded Bedrock summaries."""

from .chat_integration import LocalResourceAuthorizer
from .config import (
    BEDROCK_API_KEY,
    BEDROCK_API_MODE,
    BEDROCK_MAX_OUTPUT_TOKENS,
    BEDROCK_MODEL_ID,
    BEDROCK_MONTHLY_TOKEN_UNIT_LIMIT,
    BEDROCK_REGION,
)
from .llm_provider import BedrockConfig, BedrockProvider
from .resource_store import ResourceStore
from .summary_service import GroundedSummaryService


def build_local_bedrock_summary_service(store: ResourceStore) -> GroundedSummaryService:
    provider = BedrockProvider(
        BedrockConfig(
            region=BEDROCK_REGION,
            model_id=BEDROCK_MODEL_ID,
            api_mode=BEDROCK_API_MODE,
            api_key=BEDROCK_API_KEY,
            max_tokens=BEDROCK_MAX_OUTPUT_TOKENS,
            monthly_token_unit_limit=BEDROCK_MONTHLY_TOKEN_UNIT_LIMIT,
        ),
        store,
    )
    return GroundedSummaryService(
        authorizer=LocalResourceAuthorizer(store), provider=provider, store=store
    )
