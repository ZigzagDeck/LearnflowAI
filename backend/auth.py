"""Password, session, and role boundaries for the local LearnFlow API."""

from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import re
import secrets

from fastapi import HTTPException, Request

from .config import AUTH_SESSION_DAYS
from .resource_store import ResourceStore, ResourceStoreError, UserRecord


EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1


def normalize_email(value: str) -> str:
    email = value.strip().casefold()
    if not EMAIL_PATTERN.fullmatch(email):
        raise ValueError("Enter a valid email address.")
    return email


def normalize_display_name(value: str) -> str:
    name = " ".join(value.split())
    if len(name) < 2 or len(name) > 80:
        raise ValueError("Display name must contain between 2 and 80 characters.")
    return name


def validate_password(value: str) -> str:
    if len(value) < 8 or len(value) > 128:
        raise ValueError("Password must contain between 8 and 128 characters.")
    if value.casefold() == value or not any(character.isdigit() for character in value):
        raise ValueError("Password must include an uppercase letter and a number.")
    return value


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    actual_salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=actual_salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=32,
    )
    return digest.hex(), actual_salt.hex()


def password_matches(password: str, user: UserRecord) -> bool:
    try:
        expected, _ = hash_password(password, bytes.fromhex(user.password_salt))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(expected, user.password_hash)


def create_session(store: ResourceStore, user: UserRecord) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = (datetime.now(UTC) + timedelta(days=AUTH_SESSION_DAYS)).isoformat()
    store.create_auth_session(user.user_id, token_hash, expires_at)
    return token, expires_at


def bearer_token(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.casefold() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return token.strip()


def get_current_user(request: Request) -> UserRecord:
    token = bearer_token(request)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    try:
        user = request.app.state.resource_store.resolve_auth_session(token_hash)
    except ResourceStoreError as exc:
        raise HTTPException(status_code=503, detail="Login validation is unavailable.") from exc
    if user is None:
        raise HTTPException(status_code=401, detail="Your session has expired. Sign in again.")
    return user


def require_admin(request: Request) -> UserRecord:
    user = get_current_user(request)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator access is required.")
    return user

