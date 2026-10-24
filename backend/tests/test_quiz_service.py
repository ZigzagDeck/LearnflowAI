"""Quiz output recovery must never persist unsupported source references."""
import asyncio
import json
from unittest.mock import AsyncMock, Mock

import pytest

from backend.chunking import NormalizedChunk
from backend.contracts import QuizRequest
from backend.llm_provider import ProviderError
from backend.quiz_service import GroundedQuizService, QuizUnavailableError


def output(indices):
    return json.dumps({"questions": [{
        "question": "What do plants produce during photosynthesis?",
        "question_type": "single_answer",
        "options": ["Glucose", "Iron", "Salt", "Sand"],
        "correct_option_indices": [0], "accepted_answers": [],
        "explanation": "Plants store chemical energy in glucose.",
        "evidence_indices": indices,
    }]})


def setup_service(monkeypatch, outputs):
    chunk = NormalizedChunk(
        chunk_id="chunk-1", resource_id="source-1", source_type="pdf",
        reference_type="page", reference_number=2, chunk_index=0,
        text="Photosynthesis produces glucose.", extraction_method="native",
        chunk_version="test",
    )
    monkeypatch.setattr("backend.quiz_service._select_evidence", lambda *_: [chunk])
    authorizer = Mock(ensure_allowed=AsyncMock())
    provider = Mock(generate_quiz=AsyncMock(side_effect=outputs))
    store = Mock()
    service = GroundedQuizService(authorizer, provider, store)
    request = QuizRequest(session_id="session-1", allowed_source_ids=["source-1"], count=1)
    return service, request, provider, store


def test_valid_quiz_uses_one_call_and_hides_answer_keys(monkeypatch):
    service, request, provider, store = setup_service(monkeypatch, [output([1])])
    response = asyncio.run(service.generate(request, "user-1"))
    assert provider.generate_quiz.await_count == 1
    assert len(response.questions) == 1
    assert "correct_option_indices" not in response.questions[0].model_dump()
    assert store.create_quiz_attempt.call_args.args[-1][0]["citations"][0]["page"] == 2


@pytest.mark.parametrize("invalid", [output([0]), output([2]), "not JSON"])
def test_invalid_output_regenerates_once_with_same_evidence(monkeypatch, invalid):
    service, request, provider, store = setup_service(monkeypatch, [invalid, output([1])])
    asyncio.run(service.generate(request, "user-1"))
    assert provider.generate_quiz.await_count == 2
    assert provider.generate_quiz.await_args_list[0] == provider.generate_quiz.await_args_list[1]
    store.create_quiz_attempt.assert_called_once()


def test_repeated_invalid_evidence_is_rejected_without_saving(monkeypatch):
    service, request, provider, store = setup_service(monkeypatch, [output([0]), output([2])])
    with pytest.raises(QuizUnavailableError, match="unavailable evidence"):
        asyncio.run(service.generate(request, "user-1"))
    assert provider.generate_quiz.await_count == 2
    store.create_quiz_attempt.assert_not_called()


def test_provider_failure_does_not_retry_or_expose_secret(monkeypatch):
    service, request, provider, store = setup_service(monkeypatch, [ProviderError("secret")])
    with pytest.raises(QuizUnavailableError, match="generation is unavailable") as error:
        asyncio.run(service.generate(request, "user-1"))
    assert "secret" not in str(error.value)
    assert provider.generate_quiz.await_count == 1
    store.create_quiz_attempt.assert_not_called()
