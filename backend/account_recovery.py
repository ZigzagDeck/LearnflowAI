"""Single-use account actions, with atomic password changes and session revocation."""
from datetime import UTC, datetime, timedelta
import hashlib
import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field

from .account_mail import MailUnavailableError, mail_settings, send_account_email
from .auth import get_current_user, hash_password, normalize_email, validate_password
from .contracts import StrictModel
from .resource_store import ResourceStore, UserRecord

router = APIRouter(tags=["accounts"])
LOGGER = logging.getLogger(__name__)
GENERIC_RESET = "If an eligible account exists, a password reset email has been requested. Check your inbox."


class EmailRequest(StrictModel):
    email: str = Field(min_length=5, max_length=254)


class TokenRequest(StrictModel):
    token: str = Field(min_length=20, max_length=256)


class ResetRequest(TokenRequest):
    password: str = Field(min_length=8, max_length=128)


class AccountActions:
    def __init__(self, store: ResourceStore):
        self.store = store
        with store._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS account_actions (
                token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                purpose TEXT NOT NULL CHECK(purpose IN ('reset','verify')),
                created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE)""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_account_actions_user ON account_actions(user_id, purpose)")

    def issue(self, user: UserRecord, purpose: str) -> str | None:
        now = datetime.now(UTC)
        token = secrets.token_urlsafe(32)
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            recent = db.execute("SELECT 1 FROM account_actions WHERE user_id=? AND purpose=? AND created_at>?", (user.user_id, purpose, (now-timedelta(seconds=60)).isoformat())).fetchone()
            if recent:
                return None
            db.execute("DELETE FROM account_actions WHERE expires_at<=? OR (user_id=? AND purpose=?)", (now.isoformat(), user.user_id, purpose))
            expiry = now + (timedelta(minutes=30) if purpose == "reset" else timedelta(hours=24))
            db.execute("INSERT INTO account_actions VALUES (?,?,?,?,?)", (hashlib.sha256(token.encode()).hexdigest(),user.user_id,purpose,now.isoformat(),expiry.isoformat()))
        return token

    def consume(self, token: str, purpose: str, password: str | None = None) -> bool:
        # Hash before opening the write transaction; invalid passwords do not consume links.
        credentials = hash_password(validate_password(password)) if password is not None else None
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT a.user_id FROM account_actions a JOIN users u ON u.user_id=a.user_id WHERE token_hash=? AND purpose=? AND expires_at>? AND u.disabled=0", (token_hash,purpose,datetime.now(UTC).isoformat())).fetchone()
            if row is None:
                return False
            uid = row["user_id"]
            if purpose == "reset":
                if credentials is None:
                    return False
                db.execute("UPDATE users SET password_hash=?,password_salt=? WHERE user_id=?", (*credentials,uid))
                db.execute("DELETE FROM auth_sessions WHERE user_id=?",(uid,))
            else:
                db.execute("UPDATE users SET email_verified=1 WHERE user_id=?",(uid,))
            db.execute("DELETE FROM account_actions WHERE user_id=? AND purpose=?",(uid,purpose))
        return True


def request_account_email(store: ResourceStore, user: UserRecord, purpose: str) -> None:
    mail_settings()
    actions = AccountActions(store)
    token = actions.issue(user, purpose)
    if token:
        try:
            send_account_email(user.email, purpose, token)
        except MailUnavailableError:
            with store._connect() as db:
                db.execute("DELETE FROM account_actions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
            raise


@router.post("/auth/forgot-password")
def forgot_password(payload: EmailRequest, request: Request):
    try:
        mail_settings()  # Same unavailable response for existing and unknown accounts.
        try:
            email = normalize_email(payload.email)
        except ValueError:
            return {"message": GENERIC_RESET}
        store = request.app.state.resource_store
        user = store.get_user_by_email(email)
        if user and not user.disabled:
            try:
                request_account_email(store,user,"reset")
            except MailUnavailableError:
                LOGGER.warning("Password reset email delivery failed.")
        return {"message": GENERIC_RESET}
    except MailUnavailableError as exc:
        raise HTTPException(503, detail=str(exc)) from exc


@router.post("/auth/reset-password")
def reset_password(payload: ResetRequest, request: Request):
    try:
        valid = AccountActions(request.app.state.resource_store).consume(payload.token,"reset",payload.password)
    except ValueError as exc:
        raise HTTPException(422,detail=str(exc)) from exc
    if not valid:
        raise HTTPException(400,detail="This reset link is invalid or expired. Request a new one.")
    return {"message":"Password updated. Sign in with your new password on all devices."}


@router.post("/auth/send-verification")
def send_verification(request: Request, user: UserRecord = Depends(get_current_user)):
    if user.email_verified:
        return {"message":"Your email is already verified."}
    try:
        request_account_email(request.app.state.resource_store,user,"verify")
    except MailUnavailableError as exc:
        raise HTTPException(503,detail=str(exc)) from exc
    return {"message":"Verification email requested. Check your inbox; wait a minute before requesting another."}


@router.post("/auth/verify-email")
def verify_email(payload: TokenRequest, request: Request):
    if not AccountActions(request.app.state.resource_store).consume(payload.token,"verify"):
        raise HTTPException(400,detail="This verification link is invalid or expired. Request a new one.")
    return {"message":"Email verified. You can return to your study space."}
