"""Shared Pydantic models used by the LearnFlow backend integration.

Strict IDs and citation metadata let the UI, document retrieval and video retrieval
teams agree on interfaces without binding to a specific vector database or LLM.
"""
from enum import Enum
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceType(str, Enum):
    PDF = "pdf"
    PPTX = "pptx"
    VIDEO = "video"
    IMAGE = "image"


class MaterialStatus(str, Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class MaterialInfo(StrictModel):
    source_id: str = Field(min_length=1, max_length=160)
    source_type: SourceType
    status: MaterialStatus
    filename: str = Field(min_length=1)
    error: str | None = None


class Citation(StrictModel):
    source_id: str = Field(min_length=1)
    source_type: SourceType
    chunk_id: str = Field(min_length=1)
    # Page/slide are 1-based; timestamps are measured in seconds from video start.
    page: int | None = Field(default=None, ge=1)
    slide: int | None = Field(default=None, ge=1)
    image: int | None = Field(default=None, ge=1)
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_provenance(self):
        if self.source_type == SourceType.PDF:
            valid = self.page is not None and all(v is None for v in (self.slide, self.image, self.start_seconds, self.end_seconds))
        elif self.source_type == SourceType.PPTX:
            valid = self.slide is not None and all(v is None for v in (self.page, self.image, self.start_seconds, self.end_seconds))
        elif self.source_type == SourceType.VIDEO:
            valid = (self.start_seconds is not None and self.end_seconds is not None
                     and self.end_seconds >= self.start_seconds
                     and self.page is None and self.slide is None and self.image is None)
        else:
            valid = self.image is not None and all(
                v is None for v in (self.page, self.slide, self.start_seconds, self.end_seconds)
            )
        if not valid:
            raise ValueError("Citation metadata must match the source type")
        return self


class RetrievalHit(StrictModel):
    citation: Citation
    text: str = Field(min_length=1)
    score: float | None = Field(default=None, ge=0)


class ChatTurn(StrictModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12_000)


class ChatRequest(StrictModel):
    session_id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=4_000)
    allowed_source_ids: list[str] = Field(min_length=1, max_length=30)
    video_source_id: str | None = None
    playback_seconds: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_video(self):
        if (self.video_source_id is None) != (self.playback_seconds is None):
            raise ValueError("video_source_id and playback_seconds must be provided together")
        if self.video_source_id and self.video_source_id not in self.allowed_source_ids:
            raise ValueError("video_source_id must be an allowed source")
        return self


class ChatResponse(StrictModel):
    session_id: str
    answer: str
    grounded: bool
    citations: list[Citation]


class QuizRequest(StrictModel):
    session_id: str = Field(min_length=1)
    video_source_id: str
    playback_seconds: float = Field(ge=0)
    allowed_source_ids: list[str] = Field(min_length=1, max_length=30)
    count: int = Field(default=3, ge=1, le=10)


class QuizQuestion(StrictModel):
    question: str
    options: list[str] = Field(min_length=2, max_length=6)
    correct_option_index: int = Field(ge=0)
    explanation: str
    citations: list[Citation] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_correct_index(self):
        if self.correct_option_index >= len(self.options):
            raise ValueError("correct_option_index must point to an option")
        return self


class QuizResponse(StrictModel):
    session_id: str
    questions: list[QuizQuestion]


class APIError(StrictModel):
    detail: str
    code: str
