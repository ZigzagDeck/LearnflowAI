"""Grounded quiz generation with server-side answer keys and scoring."""

from dataclasses import dataclass
from difflib import SequenceMatcher
import json
import re
from typing import Literal, Protocol
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
from .resource_store import ResourceStore, ResourceStoreError


MAX_QUIZ_EVIDENCE_CHUNKS = 12


class QuizUnavailableError(RuntimeError):
    """A required quiz dependency is unavailable."""


class QuizAttemptError(ValueError):
    """The quiz request or submission is invalid for its current state."""


class QuizModelProvider(Protocol):
    async def generate_quiz(
        self, evidence: list[str], count: int, quiz_type: str
    ) -> str: ...


class _GeneratedQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=1_000)
    question_type: Literal["single_answer", "multiple_answer", "short_answer"]
    options: list[str] = Field(default_factory=list, max_length=6)
    correct_option_indices: list[int] = Field(default_factory=list, max_length=6)
    accepted_answers: list[str] = Field(default_factory=list, max_length=8)
    explanation: str = Field(min_length=1, max_length=2_000)
    evidence_indices: list[int] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def validate_options(self):
        normalized = [option.strip().casefold() for option in self.options]
        if self.question_type in {"single_answer", "multiple_answer"}:
            if not 3 <= len(self.options) <= 6:
                raise ValueError("Choice questions need between three and six options.")
            if any(not option for option in normalized) or len(set(normalized)) != len(normalized):
                raise ValueError("Quiz options must be non-empty and distinct.")
            indices = list(dict.fromkeys(self.correct_option_indices))
            if not indices or any(index < 0 or index >= len(self.options) for index in indices):
                raise ValueError("Correct option indices are invalid.")
            if self.question_type == "single_answer" and len(indices) != 1:
                raise ValueError("Single-answer questions need one correct option.")
            if self.question_type == "multiple_answer" and len(indices) < 2:
                raise ValueError("Multiple-answer questions need at least two correct options.")
            self.correct_option_indices = indices
            self.accepted_answers = []
        else:
            if self.options or self.correct_option_indices:
                raise ValueError("Short-answer questions cannot include options.")
            answers = [" ".join(answer.split()) for answer in self.accepted_answers]
            answers = list(dict.fromkeys(answer for answer in answers if answer))
            if not answers:
                raise ValueError("Short-answer questions need accepted answers.")
            self.accepted_answers = answers
        return self


class _GeneratedQuiz(BaseModel):
    model_config = ConfigDict(extra="forbid")
    questions: list[_GeneratedQuestion] = Field(min_length=1, max_length=20)


def _normalize_short_answer(value: str) -> str:
    return " ".join(re.findall(r"[\w]+", value.casefold(), flags=re.UNICODE))


def _short_answer_matches(submitted: str, accepted: list[str]) -> bool:
    candidate = _normalize_short_answer(submitted)
    if not candidate:
        return False
    for answer in accepted:
        expected = _normalize_short_answer(answer)
        if candidate == expected:
            return True
        if min(len(candidate), len(expected)) >= 5 and SequenceMatcher(
            None, candidate, expected
        ).ratio() >= 0.88:
            return True
    return False


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

        # Retry malformed model output once, using the same authorized evidence.
        # Provider failures (including quota errors) are never retried here.
        for attempt in range(2):
            try:
                raw = await self.provider.generate_quiz(
                    [chunk.text for chunk in evidence], request.count, request.quiz_type
                )
            except Exception as exc:
                raise QuizUnavailableError("Quiz generation is unavailable.") from exc

            try:
                generated = _parse_generated_quiz(raw, request.count)
                if any(
                    index < 1 or index > len(evidence)
                    for item in generated.questions
                    for index in item.evidence_indices
                ):
                    raise QuizUnavailableError("Quiz generation cited unavailable evidence.")
            except QuizUnavailableError:
                if attempt == 1:
                    raise
                continue
            break
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
                    question_type=item.question_type,
                    options=options,
                    max_selections=len(item.correct_option_indices),
                )
            )
            stored_questions.append(
                {
                    "question_id": question_id,
                    "question": item.question.strip(),
                    "question_type": item.question_type,
                    "options": options,
                    "correct_option_indices": item.correct_option_indices,
                    "accepted_answers": item.accepted_answers,
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

        answers = {answer.question_id: answer for answer in request.answers}
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
            answer = answers[question_id]
            question_type = str(question.get("question_type"))
            selected = list(dict.fromkeys(answer.selected_option_indices))
            if any(index < 0 or index >= len(options) for index in selected):
                raise QuizAttemptError("A selected answer is outside its option list.")
            correct_indices = [int(value) for value in question.get("correct_option_indices", [])]
            accepted_answers = [str(value) for value in question.get("accepted_answers", [])]
            if question_type == "short_answer":
                if selected or not answer.text_answer.strip():
                    raise QuizAttemptError("Every short-answer question needs a written response.")
                correct = _short_answer_matches(answer.text_answer, accepted_answers)
            elif question_type == "single_answer":
                if len(selected) != 1:
                    raise QuizAttemptError("Select one answer for every single-answer question.")
                correct = selected == correct_indices
            elif question_type == "multiple_answer":
                if not selected:
                    raise QuizAttemptError("Select answers for every multiple-answer question.")
                correct = set(selected) == set(correct_indices)
            else:
                raise QuizUnavailableError("Stored quiz type is invalid.")
            score += int(correct)
            try:
                citations = [Citation.model_validate(item) for item in question["citations"]]
            except (ValidationError, TypeError, KeyError) as exc:
                raise QuizUnavailableError("Stored quiz citations are invalid.") from exc
            results.append(
                QuizQuestionResult(
                    question_id=question_id,
                    question_type=question_type,
                    selected_option_indices=selected,
                    correct_option_indices=correct_indices,
                    submitted_text=answer.text_answer.strip(),
                    accepted_answers=accepted_answers,
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
