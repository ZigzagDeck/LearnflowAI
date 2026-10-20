"""Validate cross-team data contracts without network calls."""
import pytest
from pydantic import ValidationError

from backend.contracts import (
    Citation, SourceType, ChatRequest, QuizQuestion, RetrievalHit,
)


@pytest.mark.parametrize("data", [
    {"source_id": "pdf1", "source_type": "pdf", "chunk_id": "c1", "page": 2},
    {"source_id": "deck1", "source_type": "pptx", "chunk_id": "c2", "slide": 3},
    {"source_id": "video1", "source_type": "video", "chunk_id": "c3", "start_seconds": 0, "end_seconds": 12.5},
    {"source_id": "image1", "source_type": "image", "chunk_id": "c4", "image": 1},
])
def test_valid_citation(data):
    assert Citation.model_validate(data).source_id == data["source_id"]


@pytest.mark.parametrize("data", [
    {"source_id": "pdf1", "source_type": "pdf", "chunk_id": "c1", "slide": 3},
    {"source_id": "video1", "source_type": "video", "chunk_id": "c1", "start_seconds": 20, "end_seconds": 10},
    {"source_id": "deck1", "source_type": "pptx", "chunk_id": "c1"},
    {"source_id": "image1", "source_type": "image", "chunk_id": "c1", "page": 1},
])
def test_invalid_citation(data):
    with pytest.raises(ValidationError):
        Citation.model_validate(data)


def test_chat_video_time_requires_source_identity():
    with pytest.raises(ValidationError):
        ChatRequest(session_id="s", question="Explain", allowed_source_ids=["video1"], playback_seconds=12)
    with pytest.raises(ValidationError):
        ChatRequest(session_id="s", question="Explain", allowed_source_ids=["pdf1"], video_source_id="video1", playback_seconds=12)


def test_quiz_answer_index_must_be_valid():
    citation = Citation(source_id="pdf1", source_type=SourceType.PDF, chunk_id="c", page=1)
    with pytest.raises(ValidationError):
        QuizQuestion(question="Q", options=["A", "B"], correct_option_index=2, explanation="Why", citations=[citation])


def test_retrieval_hit_rejects_negative_scores():
    c = Citation(source_id="pdf1", source_type="pdf", chunk_id="c1", page=1)
    with pytest.raises(ValidationError):
        RetrievalHit(citation=c, text="Evidence", score=-0.3)
