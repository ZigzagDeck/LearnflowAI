"""Authenticated grounded summary endpoint."""

from fastapi import APIRouter, Depends, HTTPException, Request

from .auth import get_current_user
from .chat_service import AuthorizationError
from .contracts import SummaryRequest, SummaryResponse
from .resource_store import ResourceStoreError, UserRecord
from .summary_service import (
    GroundedSummaryService,
    SummaryAttemptError,
    SummaryUnavailableError,
)


router = APIRouter(prefix="/summary", tags=["summary"])


@router.post("", response_model=SummaryResponse)
async def generate_summary(
    payload: SummaryRequest,
    request: Request,
    user: UserRecord = Depends(get_current_user),
) -> SummaryResponse:
    service: GroundedSummaryService | None = getattr(
        request.app.state, "summary_service", None
    )
    if service is None:
        raise HTTPException(status_code=503, detail="Summary generation is not configured.")
    try:
        response = await service.generate(payload, user.user_id)
        request.app.state.resource_store.record_user_ai_usage(
            user.user_id,
            input_tokens=max(1, (len(payload.allowed_source_ids) * 1_500 + 600) // 4),
            output_tokens=max(1, (len(response.summary) + 3) // 4),
            operation="summary",
        )
        return response
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail="Requested sources are not permitted.") from exc
    except SummaryAttemptError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SummaryUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ResourceStoreError as exc:
        raise HTTPException(status_code=503, detail="Summary usage could not be recorded.") from exc
