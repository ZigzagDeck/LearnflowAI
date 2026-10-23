"""Registration, login, profile, logout, and privacy-safe admin metrics."""

from datetime import UTC, datetime
import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from .auth import (
    bearer_token,
    create_session,
    get_current_user,
    hash_password,
    normalize_display_name,
    normalize_email,
    password_matches,
    require_admin,
    validate_password,
)
from .account_recovery import request_account_email
from .account_mail import MailUnavailableError
from .contracts import AuthResponse, LoginRequest, RegisterRequest, UserProfile
from .config import EXTRACTION_PIPELINE_VERSION
from .resource_store import ResourceStoreError, UserRecord


router = APIRouter(tags=["accounts"])


def _profile(user: UserRecord) -> UserProfile:
    return UserProfile.model_validate(user.public_dict())


@router.post("/auth/register", response_model=AuthResponse)
def register(payload: RegisterRequest, request: Request) -> AuthResponse:
    try:
        email = normalize_email(payload.email)
        name = normalize_display_name(payload.display_name)
        password = validate_password(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    store = request.app.state.resource_store
    try:
        if store.get_user_by_email(email) is not None:
            raise HTTPException(status_code=409, detail="An account with this email already exists.")
        password_hash, password_salt = hash_password(password)
        user = store.create_user(
            email=email,
            display_name=name,
            password_hash=password_hash,
            password_salt=password_salt,
        )
        store.claim_legacy_data(user.user_id)
        token, expires_at = create_session(store, user)
    except HTTPException:
        raise
    except ResourceStoreError as exc:
        raise HTTPException(status_code=503, detail="Account registration is unavailable.") from exc
    # Mail failures must not prevent registration or invalidate a usable session.
    try:
        request_account_email(store, user, "verify")
    except (MailUnavailableError, ResourceStoreError, OSError):
        pass
    return AuthResponse(token=token, expires_at=expires_at, user=_profile(user))


@router.post("/auth/login", response_model=AuthResponse)
def login(payload: LoginRequest, request: Request) -> AuthResponse:
    try:
        email = normalize_email(payload.email)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Email or password is incorrect.") from exc
    store = request.app.state.resource_store
    try:
        user = store.get_user_by_email(email)
        if user is None or user.disabled or not password_matches(payload.password, user):
            raise HTTPException(status_code=401, detail="Email or password is incorrect.")
        token, expires_at = create_session(store, user)
    except HTTPException:
        raise
    except ResourceStoreError as exc:
        raise HTTPException(status_code=503, detail="Login is unavailable.") from exc
    return AuthResponse(token=token, expires_at=expires_at, user=_profile(user))


@router.get("/auth/me", response_model=UserProfile)
def me(user: UserRecord = Depends(get_current_user)) -> UserProfile:
    return _profile(user)


@router.post("/auth/logout")
def logout(
    request: Request, user: UserRecord = Depends(get_current_user)
) -> dict[str, str]:
    del user
    token_hash = hashlib.sha256(bearer_token(request).encode("utf-8")).hexdigest()
    try:
        request.app.state.resource_store.delete_auth_session(token_hash)
    except ResourceStoreError as exc:
        raise HTTPException(status_code=503, detail="Logout is unavailable.") from exc
    return {"status": "signed_out"}


@router.get("/account/export")
def export_account_data(
    request: Request, user: UserRecord = Depends(get_current_user)
) -> StreamingResponse:
    """Stream a portable JSON backup without exporting credentials or server paths."""
    store = request.app.state.resource_store
    try:
        materials = store.list_for_user(user.user_id)
        chat_sessions = store.list_chat_sessions(user.user_id)
        quizzes = store.list_quiz_attempts(user.user_id)
    except ResourceStoreError as exc:
        raise HTTPException(status_code=503, detail="Account export is unavailable.") from exc

    def encoded(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def stream_export():
        yield "{\"schema_version\":1,\"exported_at\":"
        yield encoded(datetime.now(UTC).isoformat())
        yield ",\"profile\":"
        yield encoded(
            {
                **user.public_dict(),
                "created_at": user.created_at,
                "last_seen_at": user.last_seen_at,
            }
        )
        yield ",\"materials\":["
        for index, material in enumerate(materials):
            if index:
                yield ","
            metadata = material.public_dict()
            metadata.pop("stored_filename", None)
            extraction = store.cached_extraction(
                material.resource_id, EXTRACTION_PIPELINE_VERSION
            )
            yield encoded({**metadata, "extracted_content": extraction or []})
        yield "],\"chat_sessions\":["
        for index, session_summary in enumerate(chat_sessions):
            if index:
                yield ","
            session = store.get_chat_session(
                str(session_summary["session_id"]), user.user_id
            )
            if session is not None:
                yield encoded(session)
            else:
                yield "null"
        yield "],\"quizzes\":["
        for index, quiz in enumerate(quizzes):
            if index:
                yield ","
            yield encoded(
                {
                    "quiz_id": quiz.quiz_id,
                    "session_id": quiz.session_id,
                    "source_ids": quiz.source_ids,
                    "questions": quiz.questions,
                    "status": quiz.status,
                    "answers": quiz.answers,
                    "score": quiz.score,
                    "created_at": quiz.created_at,
                    "submitted_at": quiz.submitted_at,
                }
            )
        yield "]}"

    filename = f"learnflow-export-{datetime.now(UTC).date().isoformat()}.json"
    return StreamingResponse(
        stream_export(),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/admin/users")
def admin_users(
    request: Request, admin: UserRecord = Depends(require_admin)
) -> dict[str, object]:
    del admin
    try:
        users = request.app.state.resource_store.list_admin_user_metrics()
    except ResourceStoreError as exc:
        raise HTTPException(status_code=503, detail="Admin metrics are unavailable.") from exc
    return {
        "period": datetime.now(UTC).strftime("%Y-%m"),
        "users": users,
        "privacy": "Names, email addresses, content, filenames, questions, answers, and transcripts are excluded.",
    }
