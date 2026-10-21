"""FastAPI router for the AI Mock Interview feature."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .auth import get_current_user
from .resource_store import UserRecord
from .interview_service import (
    InterviewStateError,
    InterviewUnavailableError,
    MockInterviewService,
)

router = APIRouter(prefix="/interview", tags=["interview"])


def _get_service(request: Request) -> MockInterviewService:
    service = getattr(request.app.state, "interview_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="The AI interview feature is not available. Please check your AI configuration.",
        )
    return service


class StartInterviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=128)
    job_role: str = Field(min_length=1, max_length=200)
    job_description: str = Field(default="", max_length=4000)
    resume_text: str = Field(default="", max_length=4000)
    material_ids: list[str] = Field(default_factory=list, max_length=5)
    question_count: int = Field(default=5, ge=3, le=10)
    interview_type: str = Field(default="mixed")

    @property
    def clean_type(self) -> str:
        return self.interview_type if self.interview_type in {"technical", "behavioral", "hr", "mixed"} else "mixed"


class RespondRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=3000)


@router.post("/start")
async def start_interview(
    body: StartInterviewRequest,
    user: UserRecord = Depends(get_current_user),
    service: MockInterviewService = Depends(_get_service),
):
    """Start a new mock interview session and receive the opening message."""
    try:
        material_context = ""
        if body.material_ids:
            try:
                from .config import CHUNKING_PIPELINE_VERSION
                chunks = []
                for mid in body.material_ids[:5]:
                    chunks.extend(service.store.list_chunks(mid, CHUNKING_PIPELINE_VERSION)[:3])
                if chunks:
                    material_context = "\n---\n".join(c.text[:400] for c in chunks[:6])
            except Exception:
                material_context = ""

        result = await service.start(
            session_id=body.session_id,
            user_id=user.user_id,
            job_role=body.job_role,
            job_description=body.job_description,
            resume_text=body.resume_text,
            material_context=material_context,
            question_count=body.question_count,
            interview_type=body.clean_type,
        )
        return result
    except InterviewUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=500, detail="Something went wrong starting the interview. Please try again.")


@router.post("/{interview_id}/respond")
async def respond(
    interview_id: str,
    body: RespondRequest,
    user: UserRecord = Depends(get_current_user),
    service: MockInterviewService = Depends(_get_service),
):
    """Send the candidate's answer and receive the next interviewer message."""
    try:
        result = await service.respond(
            interview_id=interview_id,
            user_id=user.user_id,
            user_message=body.message,
        )
        return result
    except InterviewStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except InterviewUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=500, detail="Something went wrong during the interview. Please try again.")


@router.post("/{interview_id}/report")
async def get_report(
    interview_id: str,
    user: UserRecord = Depends(get_current_user),
    service: MockInterviewService = Depends(_get_service),
):
    """Generate and return the structured evaluation report for a completed interview."""
    try:
        report = await service.get_report(interview_id=interview_id, user_id=user.user_id)
        return {"interview_id": interview_id, "report": report}
    except InterviewStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except InterviewUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=500, detail="Report generation failed. Please try again.")


@router.get("/history")
def interview_history(
    user: UserRecord = Depends(get_current_user),
    service: MockInterviewService = Depends(_get_service),
):
    """List all past interview sessions for the current user."""
    try:
        sessions = service.list_sessions(user.user_id)
        return {"sessions": sessions}
    except InterviewUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/{interview_id}")
def get_interview(
    interview_id: str,
    user: UserRecord = Depends(get_current_user),
    service: MockInterviewService = Depends(_get_service),
):
    """Fetch full interview session details by ID."""
    try:
        session = service.get_session(interview_id, user.user_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Interview session not found.")
        return session
    except HTTPException:
        raise
    except InterviewUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.delete("/{interview_id}")
def delete_interview(
    interview_id: str,
    user: UserRecord = Depends(get_current_user),
    service: MockInterviewService = Depends(_get_service),
):
    """Delete an interview session."""
    try:
        service.delete_session(interview_id, user.user_id)
        return {"deleted": True}
    except InterviewUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

