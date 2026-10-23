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


class YouTubeImportRequest(StrictModel):
    url: str = Field(min_length=1, max_length=2_000)


class RegisterRequest(StrictModel):
    email: str = Field(min_length=5, max_length=254)
    display_name: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(StrictModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=128)


class UserProfile(StrictModel):
    user_id: str
    email: str
    display_name: str
    role: Literal["user", "admin"]


class AuthResponse(StrictModel):
    token: str
    expires_at: str
    user: UserProfile


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


class VideoScope(StrictModel):
    source_id: str = Field(min_length=1, max_length=160)
    playback_seconds: float = Field(ge=0, allow_inf_nan=False)


class ChatRequest(StrictModel):
    session_id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=4_000)
    allowed_source_ids: list[str] = Field(min_length=1, max_length=30)
    video_source_id: str | None = None
    playback_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    video_scopes: list[VideoScope] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def validate_video(self):
        if (self.video_source_id is None) != (self.playback_seconds is None):
            raise ValueError("video_source_id and playback_seconds must be provided together")
        if self.video_source_id and self.video_source_id not in self.allowed_source_ids:
            raise ValueError("video_source_id must be an allowed source")
        scoped_ids = [scope.source_id for scope in self.video_scopes]
        if len(scoped_ids) != len(set(scoped_ids)):
            raise ValueError("video_scopes cannot contain duplicate videos")
        if self.video_source_id and self.video_source_id in scoped_ids:
            raise ValueError("A video cannot use both legacy and multi-video scopes")
        if len(scoped_ids) + (self.video_source_id is not None) > 10:
            raise ValueError("A chat can use at most 10 video scopes")
        if any(source_id not in self.allowed_source_ids for source_id in scoped_ids):
            raise ValueError("Every video scope must be an allowed source")
        return self


class ChatResponse(StrictModel):
    session_id: str
    answer: str
    grounded: bool
    citations: list[Citation]


class SummaryRequest(StrictModel):
    allowed_source_ids: list[str] = Field(min_length=1, max_length=12)
    style: Literal["concise", "detailed", "study_guide"] = "detailed"


class SummaryResponse(StrictModel):
    summary: str = Field(min_length=1, max_length=20_000)
    citations: list[Citation] = Field(min_length=1)


class QuizRequest(StrictModel):
    session_id: str = Field(min_length=1, max_length=128)
    allowed_source_ids: list[str] = Field(min_length=1, max_length=12)
    count: int = Field(default=5, ge=1, le=20)
    quiz_type: Literal["single_answer", "multiple_answer", "short_answer", "mixed"] = "single_answer"


class QuizQuestion(StrictModel):
    question_id: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=1, max_length=1_000)
    question_type: Literal["single_answer", "multiple_answer", "short_answer"]
    options: list[str] = Field(default_factory=list, max_length=6)
    max_selections: int = Field(default=1, ge=0, le=6)


class QuizAnswer(StrictModel):
    question_id: str = Field(min_length=1, max_length=64)
    selected_option_indices: list[int] = Field(default_factory=list, max_length=6)
    text_answer: str = Field(default="", max_length=2_000)


class QuizResponse(StrictModel):
    quiz_id: str = Field(min_length=1, max_length=64)
    session_id: str
    questions: list[QuizQuestion]


class QuizSubmissionRequest(StrictModel):
    session_id: str = Field(min_length=1, max_length=128)
    answers: list[QuizAnswer] = Field(min_length=1, max_length=20)


class QuizQuestionResult(StrictModel):
    question_id: str
    question_type: Literal["single_answer", "multiple_answer", "short_answer"]
    selected_option_indices: list[int]
    correct_option_indices: list[int]
    submitted_text: str = ""
    accepted_answers: list[str] = Field(default_factory=list)
    correct: bool
    explanation: str
    citations: list[Citation] = Field(min_length=1)


class QuizSubmissionResponse(StrictModel):
    quiz_id: str
    score: int = Field(ge=0)
    total: int = Field(ge=1)
    questions: list[QuizQuestionResult]


class APIError(StrictModel):
    detail: str
    code: str
