# AI model provider gateway

`backend/llm_provider.py` exposes a `ModelProvider` protocol so grounded chat is
not coupled to one model vendor. LearnFlowAI's default path is `BedrockProvider`
through the Bedrock Mantle Chat Completions endpoint. Native Boto3 Bedrock Runtime
Converse remains available for IAM principals authorized for that operation.

## Amazon Bedrock configuration

Set these values server-side. Never expose credentials through a `VITE_` variable:

- `LEARNFLOW_BEDROCK_CHAT_ENABLED=true`
- `AWS_REGION=us-east-1`
- `AWS_BEARER_TOKEN_BEDROCK`: a development Bedrock-only API key; omit this when using standard temporary AWS credentials or an IAM role
- `LEARNFLOW_BEDROCK_API_MODE=mantle_chat_completions` for project API keys, or `converse` for native Runtime authorization
- `LEARNFLOW_BEDROCK_MODEL_ID=google.gemma-4-31b` (Gemma 4 uses Mantle's `/openai/v1` route automatically)
- `LEARNFLOW_BEDROCK_MAX_OUTPUT_TOKENS=5000` (hard maximum; LearnFlow chooses a smaller per-question output budget when appropriate)
- `LEARNFLOW_BEDROCK_MONTHLY_TOKEN_UNIT_LIMIT=2000000`

The response budget is selected from the question rather than fixed: a simple
question starts around 900 tokens, explanatory questions around 1,800, and
multi-part questions around 2,800. Explicit requests for comprehensive detail
can use the configured 5,000-token ceiling. Explicit brief-answer requests stay
short. These are output ceilings, not targets; the model may finish sooner.

The Bedrock API key is sent only from the backend to the trusted regional Mantle
endpoint. In `converse` mode, AWS credentials are resolved through Boto3's normal
credential chain. The browser cannot submit an endpoint, model, or credential.

## Cost and request boundary

Each generation request receives no more than eight already-authorized evidence
chunks, each truncated to 3,000 characters. Output is capped by configuration.
Before contacting Bedrock, the provider atomically reserves conservative units
equal to the UTF-8 prompt bytes plus the complete output allowance. If the local
monthly limit would be exceeded, it sends no request. `GET /usage/bedrock`
reports this counter.

This guard is deliberately conservative and is not a currency estimate or an AWS
Budget. Deleting the local database resets it, so an account-level AWS Budget
alert remains an important independent warning.

## Local single-user integration

When explicitly enabled, `backend/chat_integration.py` connects:

1. a local authorizer that accepts only ready resources in this SQLite store;
2. filtered local hybrid retrieval;
3. Bedrock grounded-answer generation; and
4. server-owned citation metadata.

The model never chooses citation IDs. The API returns citations from the exact
retrieved chunks accepted by `GroundedChatService`. Video chunks ending after the
current playback position remain excluded.

This local authorizer is suitable for a private single-user demo. A public or
multi-user deployment must add real sign-in and resource ownership checks before
enabling chat.

## Optional generic adapter

`OpenAICompatibleProvider` is retained for explicitly configured compatible APIs.
Its server-only settings are `LEARNFLOW_MODEL_ENDPOINT`, `LEARNFLOW_MODEL_NAME`,
and `LEARNFLOW_MODEL_API_KEY`. It is not part of the default Bedrock path.

## Tests

```bash
python -m pip install -r backend/requirements-dev.txt
python -m pytest backend/tests/test_bedrock_provider.py backend/tests/test_chat_service.py -q
```

Tests use fake Mantle and Converse clients and make no AWS request. Passing mocks do not
prove live model access, production authentication, or sentence-level grounding.
