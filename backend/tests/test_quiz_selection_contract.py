"""Public quiz selection limits must not reveal the hidden answer count."""
import asyncio
import json
from unittest.mock import AsyncMock, Mock

import pytest

from backend.chunking import NormalizedChunk
from backend.contracts import QuizRequest, QuizAnswer, QuizSubmissionRequest
from backend.quiz_service import GroundedQuizService


@pytest.mark.parametrize('kind,correct,expected', [('single_answer',[0],1),('multiple_answer',[0,2],4),('short_answer',[],0)])
def test_public_selection_limit_is_based_on_options(monkeypatch,kind,correct,expected):
    chunk=NormalizedChunk(chunk_id='c1',resource_id='s1',source_type='pdf',reference_type='page',reference_number=1,chunk_index=0,text='Plants absorb light and water.',extraction_method='native',chunk_version='test')
    monkeypatch.setattr('backend.quiz_service._select_evidence',lambda *_:[chunk])
    raw={'questions':[{'question':'What do plants absorb?','question_type':kind,'options':[] if kind=='short_answer' else ['Light','Sand','Water','Iron'],'correct_option_indices':correct,'accepted_answers':['light'] if kind=='short_answer' else [],'explanation':'The supplied page mentions light and water.','evidence_indices':[1]}]}
    store=Mock();provider=Mock(generate_quiz=AsyncMock(return_value=json.dumps(raw)))
    service=GroundedQuizService(Mock(ensure_allowed=AsyncMock()),provider,store)
    response=asyncio.run(service.generate(QuizRequest(session_id='session',allowed_source_ids=['s1'],count=1,quiz_type=kind),'user'))
    public=response.questions[0].model_dump()
    assert public['max_selections']==expected
    assert 'correct_option_indices' not in public
    assert 'accepted_answers' not in public


def test_multiple_answer_scoring_still_requires_the_exact_set():
    question={'question_id':'q1','question_type':'multiple_answer','options':['A','B','C','D'],'correct_option_indices':[0,2],'accepted_answers':[],'explanation':'Source supports A and C.','citations':[{'source_id':'s1','source_type':'pdf','chunk_id':'c1','page':1}]}
    for selected,score in [([0],0),([0,2],1),([0,2,3],0)]:
        store=Mock()
        store.get_quiz_attempt.return_value=Mock(session_id='session',status='ready',questions=[question])
        service=GroundedQuizService(Mock(),Mock(),store)
        result=service.submit('quiz',QuizSubmissionRequest(session_id='session',answers=[QuizAnswer(question_id='q1',selected_option_indices=selected)]),'user')
        assert result.score==score
