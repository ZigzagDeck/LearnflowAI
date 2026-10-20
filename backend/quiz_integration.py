"""Single-user local wiring for grounded Bedrock quizzes."""

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
from .quiz_service import GroundedQuizService
from .resource_store import ResourceStore


def build_local_bedrock_quiz_service(store: ResourceStore) -> GroundedQuizService:
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
    return GroundedQuizService(
        authorizer=LocalResourceAuthorizer(store),
        provider=provider,
        store=store,
    )
