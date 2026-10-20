"""Grounded quiz HTTP endpoints."""

from fastapi import APIRouter, HTTPException, Request

from .chat_service import AuthorizationError
from .contracts import (
    QuizRequest,
    QuizResponse,
    QuizSubmissionRequest,
    QuizSubmissionResponse,
)
from .quiz_service import GroundedQuizService, QuizAttemptError, QuizUnavailableError


router = APIRouter(prefix="/quiz", tags=["quiz"])


@router.post("", response_model=QuizResponse)
async def generate_quiz(payload: QuizRequest, request: Request) -> QuizResponse:
    service: GroundedQuizService | None = getattr(
        request.app.state, "quiz_service", None
    )
    if service is None:
        raise HTTPException(status_code=503, detail="Quiz generation is not configured.")
    try:
        return await service.generate(payload)
    except AuthorizationError as exc:
        raise HTTPException(
            status_code=403, detail="Requested sources are not permitted."
        ) from exc
    except QuizAttemptError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except QuizUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/{quiz_id}/submit", response_model=QuizSubmissionResponse)
def submit_quiz(
    quiz_id: str, payload: QuizSubmissionRequest, request: Request
) -> QuizSubmissionResponse:
    service: GroundedQuizService | None = getattr(
        request.app.state, "quiz_service", None
    )
    if service is None:
        raise HTTPException(status_code=503, detail="Quiz scoring is not configured.")
    try:
        return service.submit(quiz_id, payload)
    except QuizAttemptError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except QuizUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
