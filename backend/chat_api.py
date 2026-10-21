"""HTTP endpoint for AI chat. Defaults to 503 until securely configured."""
from fastapi import APIRouter, Depends, HTTPException, Request

from .auth import get_current_user
from .contracts import ChatRequest, ChatResponse
from .chat_service import (
    AuthorizationError,
    ChatUnavailableError,
    GroundedChatService,
)
from .resource_store import ResourceStoreError, UserRecord

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    request: Request,
    user: UserRecord = Depends(get_current_user),
) -> ChatResponse:
    service: GroundedChatService | None = getattr(
        request.app.state, "chat_service", None
    )
    if service is None:
        raise HTTPException(
            status_code=503, detail="Chat integrations are not configured."
        )
    try:
        response = await service.answer(payload, user.user_id)
        request.app.state.resource_store.append_chat_turn(
            user.user_id,
            payload.session_id,
            payload.question,
            response.answer,
            payload.allowed_source_ids,
            [citation.model_dump(mode="json") for citation in response.citations],
        )
        estimated_input = max(
            1,
            (
                len(payload.question)
                + len(response.citations) * 1_200
                + 500
                + 3
            )
            // 4,
        )
        estimated_output = max(1, (len(response.answer) + 3) // 4)
        request.app.state.resource_store.record_user_ai_usage(
            user.user_id,
            input_tokens=estimated_input,
            output_tokens=estimated_output,
            operation="chat",
        )
        return response
    except AuthorizationError as exc:
        raise HTTPException(
            status_code=403, detail="Requested sources are not permitted."
        ) from exc
    except ChatUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ResourceStoreError as exc:
        raise HTTPException(status_code=503, detail="Chat history could not be saved.") from exc


@router.get("/chat/history")
def chat_history(
    request: Request,
    user: UserRecord = Depends(get_current_user),
) -> dict[str, object]:
    try:
        return {
            "sessions": request.app.state.resource_store.list_chat_sessions(
                user.user_id
            )
        }
    except ResourceStoreError as exc:
        raise HTTPException(status_code=503, detail="Chat history is unavailable.") from exc


@router.get("/chat/history/{session_id}")
def chat_history_session(
    session_id: str,
    request: Request,
    user: UserRecord = Depends(get_current_user),
) -> dict[str, object]:
    try:
        session = request.app.state.resource_store.get_chat_session(
            session_id, user.user_id
        )
    except ResourceStoreError as exc:
        raise HTTPException(status_code=503, detail="Chat history is unavailable.") from exc
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session was not found.")
    return session


@router.delete("/chat/history/{session_id}")
def delete_chat_history(
    session_id: str,
    request: Request,
    user: UserRecord = Depends(get_current_user),
) -> dict[str, str]:
    try:
        deleted = request.app.state.resource_store.delete_chat_session(
            session_id, user.user_id
        )
    except ResourceStoreError as exc:
        raise HTTPException(status_code=503, detail="Chat history could not be deleted.") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Chat session was not found.")
    return {"session_id": session_id, "status": "deleted"}
