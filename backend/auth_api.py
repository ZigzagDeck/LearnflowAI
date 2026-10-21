"""Registration, login, profile, logout, and privacy-safe admin metrics."""

from datetime import UTC, datetime
import hashlib

from fastapi import APIRouter, Depends, HTTPException, Request

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
from .contracts import AuthResponse, LoginRequest, RegisterRequest, UserProfile
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
        "privacy": "Content, filenames, questions, answers, and full email addresses are excluded.",
    }
