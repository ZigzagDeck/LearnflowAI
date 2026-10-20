"""Amazon Bedrock Converse adapter tests without live AWS requests."""

import asyncio

import pytest

from backend.llm_provider import (
    BEDROCK_USAGE_PROVIDER_KEY,
    BedrockConfig,
    BedrockConverseProvider,
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
        BedrockConverseProvider(
            BedrockConfig(
                region="us-east-1",
                model_id="amazon.nova-lite-v1:0",
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
