"""Grounded quiz generation with server-side answer keys and scoring."""

from dataclasses import dataclass
import json
from typing import Protocol
import uuid

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .chat_service import AuthorizationError, SourceAuthorizer
from .chunking import NormalizedChunk
from .config import CHUNKING_PIPELINE_VERSION
from .contracts import (
    Citation,
    QuizQuestion,
    QuizQuestionResult,
    QuizRequest,
    QuizResponse,
    QuizSubmissionRequest,
    QuizSubmissionResponse,
    SourceType,
)
from .llm_provider import ProviderError
from .resource_store import ResourceStore, ResourceStoreError


MAX_QUIZ_EVIDENCE_CHUNKS = 12


class QuizUnavailableError(RuntimeError):
    """A required quiz dependency is unavailable."""


class QuizAttemptError(ValueError):
    """The quiz request or submission is invalid for its current state."""


class QuizModelProvider(Protocol):
    async def generate_quiz(self, evidence: list[str], count: int) -> str: ...


class _GeneratedQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=1_000)
    options: list[str] = Field(min_length=4, max_length=4)
    correct_option_index: int = Field(ge=0, le=3)
    explanation: str = Field(min_length=1, max_length=2_000)
    evidence_indices: list[int] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def validate_options(self):
        normalized = [option.strip().casefold() for option in self.options]
        if any(not option for option in normalized) or len(set(normalized)) != 4:
            raise ValueError("Quiz options must be non-empty and distinct.")
        return self


class _GeneratedQuiz(BaseModel):
    model_config = ConfigDict(extra="forbid")
    questions: list[_GeneratedQuestion] = Field(min_length=1, max_length=10)


def _citation_for_chunk(chunk: NormalizedChunk) -> Citation:
    provenance: dict[str, int | float | None]
    if chunk.source_type == SourceType.VIDEO.value:
        provenance = {
            "start_seconds": chunk.start_seconds,
            "end_seconds": chunk.end_seconds,
        }
    else:
        provenance = {chunk.reference_type: chunk.reference_number}
    return Citation(
        source_id=chunk.resource_id,
        source_type=SourceType(chunk.source_type),
        chunk_id=chunk.chunk_id,
        **provenance,
    )


def _sample_chunks(chunks: list[NormalizedChunk], count: int) -> list[NormalizedChunk]:
    if count >= len(chunks):
        return chunks
    if count == 1:
        return [chunks[len(chunks) // 2]]
    return [
        chunks[round(index * (len(chunks) - 1) / (count - 1))]
        for index in range(count)
    ]


def _select_evidence(
    store: ResourceStore, source_ids: list[str]
) -> list[NormalizedChunk]:
    unique_ids = list(dict.fromkeys(source_ids))[:12]
    available = [
        store.list_chunks(source_id, CHUNKING_PIPELINE_VERSION)
        for source_id in unique_ids
    ]
    available = [chunks for chunks in available if chunks]
    if not available:
        return []

    base, remainder = divmod(MAX_QUIZ_EVIDENCE_CHUNKS, len(available))
    selected: list[NormalizedChunk] = []
    for index, chunks in enumerate(available):
        take = min(len(chunks), base + (1 if index < remainder else 0))
        selected.extend(_sample_chunks(chunks, max(1, take)))
    return selected[:MAX_QUIZ_EVIDENCE_CHUNKS]


def _parse_generated_quiz(raw: str, expected_count: int) -> _GeneratedQuiz:
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise QuizUnavailableError("Quiz generation returned invalid JSON.")
    try:
        quiz = _GeneratedQuiz.model_validate(json.loads(raw[start : end + 1]))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise QuizUnavailableError("Quiz generation returned an invalid structure.") from exc
    if len(quiz.questions) != expected_count:
        raise QuizUnavailableError("Quiz generation returned the wrong number of questions.")
    normalized = [question.question.strip().casefold() for question in quiz.questions]
    if len(set(normalized)) != len(normalized):
        raise QuizUnavailableError("Quiz generation returned duplicate questions.")
    return quiz


@dataclass
class GroundedQuizService:
    authorizer: SourceAuthorizer
    provider: QuizModelProvider
    store: ResourceStore

    async def generate(self, request: QuizRequest, user_id: str) -> QuizResponse:
        try:
            await self.authorizer.ensure_allowed(
                user_id, request.allowed_source_ids
            )
        except AuthorizationError:
            raise
        except Exception as exc:
            raise QuizUnavailableError("Source authorization unavailable.") from exc

        try:
            evidence = _select_evidence(self.store, request.allowed_source_ids)
        except ResourceStoreError as exc:
            raise QuizUnavailableError("Quiz evidence is unavailable.") from exc
        if not evidence:
            raise QuizAttemptError("The selected materials contain no quiz-ready text.")

        try:
            raw = await self.provider.generate_quiz(
                [chunk.text for chunk in evidence], request.count
            )
        except ProviderError as exc:
            raise QuizUnavailableError("Quiz generation is unavailable.") from exc
        except Exception as exc:
            raise QuizUnavailableError("Quiz generation is unavailable.") from exc

        generated = _parse_generated_quiz(raw, request.count)
        stored_questions: list[dict[str, object]] = []
        public_questions: list[QuizQuestion] = []
        for item in generated.questions:
            evidence_indices = list(dict.fromkeys(item.evidence_indices))
            if any(index < 1 or index > len(evidence) for index in evidence_indices):
                raise QuizUnavailableError("Quiz generation cited unavailable evidence.")
            citations = [
                _citation_for_chunk(evidence[index - 1])
                for index in evidence_indices
            ]
            question_id = uuid.uuid4().hex
            options = [option.strip() for option in item.options]
            public_questions.append(
                QuizQuestion(
                    question_id=question_id,
                    question=item.question.strip(),
                    options=options,
                )
            )
            stored_questions.append(
                {
                    "question_id": question_id,
                    "question": item.question.strip(),
                    "options": options,
                    "correct_option_index": item.correct_option_index,
                    "explanation": item.explanation.strip(),
                    "citations": [citation.model_dump(mode="json") for citation in citations],
                }
            )

        quiz_id = uuid.uuid4().hex
        try:
            self.store.create_quiz_attempt(
                quiz_id,
                user_id,
                request.session_id,
                request.allowed_source_ids,
                stored_questions,
            )
        except ResourceStoreError as exc:
            raise QuizUnavailableError("Generated quiz could not be saved.") from exc
        return QuizResponse(
            quiz_id=quiz_id,
            session_id=request.session_id,
            questions=public_questions,
        )

    def submit(
        self, quiz_id: str, request: QuizSubmissionRequest, user_id: str
    ) -> QuizSubmissionResponse:
        try:
            attempt = self.store.get_quiz_attempt(quiz_id, user_id)
        except ResourceStoreError as exc:
            raise QuizUnavailableError("Quiz data is unavailable.") from exc
        if attempt is None or attempt.session_id != request.session_id:
            raise QuizAttemptError("Quiz was not found.")
        if attempt.status != "ready":
            raise QuizAttemptError("This quiz has already been submitted.")

        answers = {answer.question_id: answer.option_index for answer in request.answers}
        if len(answers) != len(request.answers):
            raise QuizAttemptError("Each quiz question must be answered once.")
        expected_ids = {str(question["question_id"]) for question in attempt.questions}
        if set(answers) != expected_ids:
            raise QuizAttemptError("Every quiz question must be answered.")

        score = 0
        results: list[QuizQuestionResult] = []
        for question in attempt.questions:
            question_id = str(question["question_id"])
            options = question.get("options")
            if not isinstance(options, list):
                raise QuizUnavailableError("Stored quiz data is invalid.")
            selected = answers[question_id]
            correct_index = int(question["correct_option_index"])
            if selected >= len(options):
                raise QuizAttemptError("A selected answer is outside its option list.")
            correct = selected == correct_index
            score += int(correct)
            try:
                citations = [Citation.model_validate(item) for item in question["citations"]]
            except (ValidationError, TypeError, KeyError) as exc:
                raise QuizUnavailableError("Stored quiz citations are invalid.") from exc
            results.append(
                QuizQuestionResult(
                    question_id=question_id,
                    selected_option_index=selected,
                    correct_option_index=correct_index,
                    correct=correct,
                    explanation=str(question["explanation"]),
                    citations=citations,
                )
            )

        serialized_answers = [answer.model_dump(mode="json") for answer in request.answers]
        try:
            self.store.complete_quiz_attempt(
                quiz_id, user_id, serialized_answers, score
            )
        except ResourceStoreError as exc:
            raise QuizUnavailableError("Quiz result could not be saved.") from exc
        return QuizSubmissionResponse(
            quiz_id=quiz_id,
            score=score,
            total=len(results),
            questions=results,
        )
