"""Single-user local wiring for the mock interview service with Bedrock."""

from .config import (
    BEDROCK_API_KEY,
    BEDROCK_API_MODE,
    BEDROCK_MAX_OUTPUT_TOKENS,
    BEDROCK_MODEL_ID,
    BEDROCK_MONTHLY_TOKEN_UNIT_LIMIT,
    BEDROCK_REGION,
)
from .llm_provider import BedrockConfig, BedrockProvider
from .interview_service import BedrockInterviewProvider, MockInterviewService
from .resource_store import ResourceStore


def build_local_bedrock_interview_service(store: ResourceStore) -> MockInterviewService:
    bedrock = BedrockProvider(
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
    provider = BedrockInterviewProvider(bedrock=bedrock)
    return MockInterviewService(provider=provider, store=store)
