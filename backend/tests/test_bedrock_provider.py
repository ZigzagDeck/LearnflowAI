"""Amazon Bedrock Mantle and Converse adapter tests without live AWS requests."""

import asyncio

import httpx
import pytest

from backend.llm_provider import (
    BEDROCK_USAGE_PROVIDER_KEY,
    BedrockConfig,
    BedrockProvider,
    ProviderError,
)
from backend.resource_store import ResourceStore


class FakeBedrockClient:
    def __init__(self, response=None, error=None):
        self.response = response or {
            "output": {"message": {"content": [{"text": "A grounded answer."}]}}
        }
        self.error = error
        self.request = None

    def converse(self, **request):
        self.request = request
        if self.error:
            raise self.error
        return self.response


def provider(tmp_path, client, *, monthly_limit=20_000):
    store = ResourceStore(tmp_path / "learnflow.db")
    return (
        BedrockProvider(
            BedrockConfig(
                region="us-east-1",
                model_id="amazon.nova-lite-v1:0",
                api_mode="converse",
                max_tokens=128,
                monthly_token_unit_limit=monthly_limit,
            ),
            store,
            client=client,
        ),
        store,
    )


def test_bedrock_converse_uses_only_bounded_evidence_and_tracks_usage(tmp_path):
    client = FakeBedrockClient()
    bedrock, store = provider(tmp_path, client)

    answer = asyncio.run(
        bedrock.answer("What is caching?", ["Caching stores reusable data."])
    )

    assert answer == "A grounded answer."
    assert client.request["modelId"] == "amazon.nova-lite-v1:0"
    assert client.request["inferenceConfig"]["maxTokens"] == 128
    prompt = client.request["messages"][0]["content"][0]["text"]
    assert "Caching stores reusable data." in prompt
    assert store.current_monthly_usage(BEDROCK_USAGE_PROVIDER_KEY)[1] > 128


def test_bedrock_limit_blocks_request_before_client_call(tmp_path):
    client = FakeBedrockClient()
    bedrock, _ = provider(tmp_path, client, monthly_limit=1)

    with pytest.raises(ProviderError, match="monthly Amazon Bedrock limit"):
        asyncio.run(bedrock.answer("Question", ["Evidence"]))
    assert client.request is None


def test_bedrock_errors_do_not_expose_credentials_or_provider_details(tmp_path):
    client = FakeBedrockClient(error=RuntimeError("secret-token provider detail"))
    bedrock, _ = provider(tmp_path, client)

    with pytest.raises(ProviderError) as error:
        asyncio.run(bedrock.answer("Question", ["Evidence"]))
    assert "secret-token" not in str(error.value)


def test_bedrock_rejects_empty_evidence_without_reserving_usage(tmp_path):
    client = FakeBedrockClient()
    bedrock, store = provider(tmp_path, client)

    with pytest.raises(ProviderError, match="approved evidence"):
        asyncio.run(bedrock.answer("Question", []))
    assert store.current_monthly_usage(BEDROCK_USAGE_PROVIDER_KEY)[1] == 0


def test_bedrock_mantle_uses_project_endpoint_and_tracks_usage(tmp_path):
    request_data = {}

    def handler(request: httpx.Request) -> httpx.Response:
        request_data["url"] = str(request.url)
        request_data["authorization"] = request.headers["authorization"]
        request_data["payload"] = __import__("json").loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Mantle answer."}}]},
        )

    store = ResourceStore(tmp_path / "learnflow.db")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    bedrock = BedrockProvider(
        BedrockConfig(
            region="us-east-1",
            model_id="google.gemma-4-31b",
            api_mode="mantle_chat_completions",
            api_key="bedrock-secret",
            max_tokens=128,
        ),
        store,
        client=client,
    )

    answer = asyncio.run(bedrock.answer("What is caching?", ["Approved evidence."]))

    assert answer == "Mantle answer."
    assert request_data["url"] == (
        "https://bedrock-mantle.us-east-1.api.aws/openai/v1/chat/completions"
    )
    assert request_data["authorization"] == "Bearer bedrock-secret"
    assert request_data["payload"]["model"] == "google.gemma-4-31b"
    assert "Approved evidence." in request_data["payload"]["messages"][1]["content"]
    assert store.current_monthly_usage(BEDROCK_USAGE_PROVIDER_KEY)[1] > 128


def test_bedrock_allows_50k_for_explicitly_detailed_answers(tmp_path):
    request_data = {}

    def handler(request: httpx.Request) -> httpx.Response:
        request_data["payload"] = __import__("json").loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Detailed answer."}}]},
        )

    store = ResourceStore(tmp_path / "learnflow.db")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    bedrock = BedrockProvider(
        BedrockConfig(
            region="us-east-1",
            model_id="google.gemma-4-31b",
            api_mode="mantle_chat_completions",
            api_key="bedrock-secret",
            max_tokens=50_000,
        ),
        store,
        client=client,
    )

    answer = asyncio.run(
        bedrock.answer("Explain this in detail.", ["Approved evidence."])
    )

    assert answer == "Detailed answer."
    assert request_data["payload"]["max_tokens"] == 50_000


def test_bedrock_rejects_output_limit_above_50k():
    with pytest.raises(ProviderError, match="output limit"):
        BedrockConfig(
            region="us-east-1",
            model_id="google.gemma-4-31b",
            api_mode="mantle_chat_completions",
            api_key="bedrock-secret",
            max_tokens=50_001,
        )
