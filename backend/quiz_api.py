"""Grounded quiz HTTP endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request

from .auth import get_current_user
from .chat_service import AuthorizationError
from .contracts import (
    QuizRequest,
    QuizResponse,
    QuizSubmissionRequest,
    QuizSubmissionResponse,
)
from .quiz_service import GroundedQuizService, QuizAttemptError, QuizUnavailableError
from .resource_store import ResourceStoreError, UserRecord


router = APIRouter(prefix="/quiz", tags=["quiz"])


@router.post("", response_model=QuizResponse)
async def generate_quiz(
    payload: QuizRequest,
    request: Request,
    user: UserRecord = Depends(get_current_user),
) -> QuizResponse:
    service: GroundedQuizService | None = getattr(
        request.app.state, "quiz_service", None
    )
    if service is None:
        raise HTTPException(status_code=503, detail="Quiz generation is not configured.")
    try:
        response = await service.generate(payload, user.user_id)
        rendered = sum(
            len(question.question) + sum(len(option) for option in question.options)
            for question in response.questions
        )
        request.app.state.resource_store.record_user_ai_usage(
            user.user_id,
            input_tokens=max(1, (len(payload.allowed_source_ids) * 1_200 + 500) // 4),
            output_tokens=max(1, rendered // 4),
            operation="quiz",
        )
        return response
    except AuthorizationError as exc:
        raise HTTPException(
            status_code=403, detail="Requested sources are not permitted."
        ) from exc
    except QuizAttemptError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except QuizUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ResourceStoreError as exc:
        raise HTTPException(status_code=503, detail="Quiz usage could not be recorded.") from exc


@router.post("/{quiz_id}/submit", response_model=QuizSubmissionResponse)
def submit_quiz(
    quiz_id: str,
    payload: QuizSubmissionRequest,
    request: Request,
    user: UserRecord = Depends(get_current_user),
) -> QuizSubmissionResponse:
    service: GroundedQuizService | None = getattr(
        request.app.state, "quiz_service", None
    )
    if service is None:
        raise HTTPException(status_code=503, detail="Quiz scoring is not configured.")
    try:
        return service.submit(quiz_id, payload, user.user_id)
    except QuizAttemptError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except QuizUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
