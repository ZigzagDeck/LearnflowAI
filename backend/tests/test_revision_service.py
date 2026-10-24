"""Revision security, grounding, scoring and bounded provider behavior."""
import asyncio
import json
from unittest.mock import AsyncMock, Mock

import pytest

from backend.chat_service import AuthorizationError
from backend.chunking import NormalizedChunk
from backend.contracts import QuizAnswer, QuizSubmissionRequest, RevisionRequest
from backend.quiz_service import GroundedQuizService, QuizAttemptError, QuizUnavailableError
from backend.revision_service import RevisionService
from backend.llm_provider import ProviderError


@pytest.fixture
def revision(configure_local_services):
    store = configure_local_services['store']
    user_id = configure_local_services['user'].user_id
    questions = []
    for qid in ['missed', 'correct']:
        questions.append(dict(question_id=qid, question=f'Original {qid} question?',
                              question_type='single_answer', options=['A', 'B', 'C', 'D'],
                              correct_option_indices=[0], accepted_answers=[], explanation='Read about evaporation.',
                              citations=[dict(source_id='s1', source_type='pdf', chunk_id='c1', page=1)]))
    store.create_quiz_attempt('original', user_id, 'session', ['s1'], questions)
    store.complete_quiz_attempt('original', user_id, [
        dict(question_id='missed', selected_option_indices=[1], text_answer=''),
        dict(question_id='correct', selected_option_indices=[0], text_answer=''),
    ], 1)
    chunk = NormalizedChunk(chunk_id='c1', resource_id='s1', source_type='pdf', reference_type='page',
                            reference_number=1, chunk_index=0, text='Heat changes liquid water into vapour.',
                            extraction_method='native', chunk_version='test')
    store.list_chunks = Mock(return_value=[chunk])
    raw = json.dumps(dict(questions=[dict(question='A puddle shrinks on a sunny day. Which process explains this?',
                       question_type='single_answer', options=['Evaporation', 'Freezing', 'Rain', 'Snow'],
                       correct_option_indices=[0], accepted_answers=[], explanation='Heat forms vapour.', evidence_indices=[1])]))
    provider = Mock(generate_revision_quiz=AsyncMock(return_value=raw))
    quiz = GroundedQuizService(Mock(ensure_allowed=AsyncMock()), provider, store)
    return RevisionService(quiz), user_id, raw


def test_plan_uses_server_answers_and_exact_cited_passage_without_ai(revision):
    service, uid, _ = revision
    plan = asyncio.run(service.plan('original', uid))
    assert plan.missed_count == 1
    assert [t.question_id for t in plan.targets] == ['missed']
    assert plan.targets[0].passages[0].citation.chunk_id == 'c1'
    assert 'vapour' in plan.targets[0].passages[0].text
    service.quiz.provider.generate_revision_quiz.assert_not_called()


def test_owner_and_submission_required(revision):
    service, uid, _ = revision
    with pytest.raises(QuizAttemptError):
        asyncio.run(service.plan('original', 'other-user'))
    service.quiz.store.create_quiz_attempt('unsubmitted', uid, 'session', ['s1'], [])
    with pytest.raises(QuizAttemptError):
        asyncio.run(service.plan('unsubmitted', uid))


def test_source_access_rechecked_before_reading(revision):
    service, uid, _ = revision
    service.quiz.authorizer.ensure_allowed.side_effect = AuthorizationError('unavailable')
    with pytest.raises(AuthorizationError):
        asyncio.run(service.plan('original', uid))


@pytest.mark.parametrize('ids', [['correct'], ['invented'], ['missed', 'missed']])
def test_client_cannot_choose_correct_unknown_or_duplicate_questions(revision, ids):
    service, uid, _ = revision
    with pytest.raises(QuizAttemptError):
        asyncio.run(service.generate('original', RevisionRequest(session_id='practice', question_ids=ids), uid))
    service.quiz.provider.generate_revision_quiz.assert_not_called()


def test_missing_chunk_does_not_fall_back_to_unrelated_content(revision):
    service, uid, _ = revision
    service.quiz.store.list_chunks.return_value = []
    plan = asyncio.run(service.plan('original', uid))
    assert plan.targets[0].passages == []
    with pytest.raises(QuizAttemptError):
        asyncio.run(service.generate('original', RevisionRequest(session_id='practice', question_ids=['missed']), uid))


def test_fresh_practice_is_private_and_uses_existing_scoring(revision):
    service, uid, _ = revision
    response = asyncio.run(service.generate('original', RevisionRequest(session_id='practice', question_ids=['missed']), uid))
    public = response.model_dump()
    assert response.parent_quiz_id == 'original'
    assert 'correct_option_indices' not in public['questions'][0]
    stored = service.quiz.store.get_quiz_attempt(response.quiz_id, uid)
    assert stored.questions[0]['revision_question_id'] == 'missed'
    assert stored.source_ids == ['s1']
    result = service.quiz.submit(response.quiz_id, QuizSubmissionRequest(session_id='practice', answers=[
        QuizAnswer(question_id=response.questions[0].question_id, selected_option_indices=[0])]), uid)
    assert result.score == 1
    assert service.quiz.store.get_quiz_attempt('original', uid).score == 1
    call = service.quiz.provider.generate_revision_quiz.call_args.args
    assert call[0] == ['Heat changes liquid water into vapour.']
    assert call[1] == 'Original missed question?'


@pytest.mark.parametrize('bad_kind', ['repeated', 'invalid_reference'])
def test_invalid_practice_retries_once_then_fails_without_saving(revision, bad_kind):
    service, uid, raw = revision
    payload = json.loads(raw)
    if bad_kind == 'repeated':
        payload['questions'][0]['question'] = 'Original missed question?'
    else:
        payload['questions'][0]['evidence_indices'] = [99]
    service.quiz.provider.generate_revision_quiz.return_value = json.dumps(payload)
    with pytest.raises(QuizUnavailableError):
        asyncio.run(service.generate('original', RevisionRequest(session_id='practice', question_ids=['missed']), uid))
    assert service.quiz.provider.generate_revision_quiz.call_count == 2
    assert len(service.quiz.store.list_quiz_attempts(uid)) == 1


def test_provider_failure_keeps_original_result_and_does_not_retry(revision):
    service, uid, _ = revision
    service.quiz.provider.generate_revision_quiz.side_effect = ProviderError('offline')
    with pytest.raises(QuizUnavailableError):
        asyncio.run(service.generate('original', RevisionRequest(session_id='practice', question_ids=['missed']), uid))
    assert service.quiz.provider.generate_revision_quiz.call_count == 1
    assert service.quiz.store.get_quiz_attempt('original', uid).status == 'submitted'


def test_revision_http_requires_auth_and_validates_selection(revision, configure_local_services):
    from fastapi.testclient import TestClient
    import backend.main as main
    service, uid, _ = revision
    with TestClient(main.app) as client:
        main.app.state.quiz_service = service.quiz
        assert client.get('/quiz/original/revision').status_code == 401
        client.headers['Authorization'] = 'Bearer ' + configure_local_services['token']
        plan = client.get('/quiz/original/revision')
        assert plan.status_code == 200
        assert plan.json()['targets'][0]['question_id'] == 'missed'
        assert client.get('/quiz/unknown/revision').status_code == 409
        assert client.post('/quiz/original/revision', json={'session_id':'p', 'question_ids':['correct']}).status_code == 422
        assert client.post('/quiz/original/revision', json={'session_id':'p', 'question_ids':['missed'] * 4}).status_code == 422
        practice = client.post('/quiz/original/revision', json={'session_id':'p', 'question_ids':['missed']})
        assert practice.status_code == 200
        question = practice.json()['questions'][0]
        assert 'correct_option_indices' not in question
        scored = client.post('/quiz/' + practice.json()['quiz_id'] + '/submit', json={
            'session_id':'p', 'answers':[{'question_id':question['question_id'], 'selected_option_indices':[0]}]})
        assert scored.status_code == 200 and scored.json()['score'] == 1


def test_revision_prompt_separates_focus_from_evidence(revision, monkeypatch):
    from backend.llm_provider import BedrockConfig, BedrockProvider
    service, uid, raw = revision
    provider = BedrockProvider(BedrockConfig(region='us-east-1', model_id='test', api_key='fake-test-key', max_tokens=1500), service.quiz.store)
    complete = Mock(return_value=raw)
    monkeypatch.setattr(provider, '_complete_sync', complete)
    asyncio.run(provider.generate_revision_quiz(['Only authorized source text.'], 'Focus question?', ['Old stem?']))
    system, prompt, budget = complete.call_args.args
    assert 'Only authorized source text.' in prompt
    assert 'Focus question?' in prompt and 'Old stem?' in prompt
    assert 'NEW application or reasoning' in prompt and 'one-based' in prompt
    assert 'untrusted data' in prompt
    assert budget <= 1500
