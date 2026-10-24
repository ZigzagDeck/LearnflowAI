"""Password reset/verification boundaries and backwards-compatible accounts."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import hashlib
from email import policy
from email.parser import BytesParser

from fastapi.testclient import TestClient
import pytest

from backend import account_recovery as recovery
from backend.account_mail import MailUnavailableError, send_account_email
from backend.auth import create_session, password_matches
from backend.main import app
from backend.resource_store import ResourceStore


@pytest.fixture
def accounts(configure_local_services, monkeypatch):
    from backend import rate_limit
    rate_limit._BUCKETS.clear()
    monkeypatch.setattr(rate_limit, "AUTH_REQUESTS_PER_MINUTE", 60)
    monkeypatch.setenv("LEARNFLOW_EMAIL_MODE", "preview")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("LEARNFLOW_PUBLIC_APP_URL", "http://localhost:5173")
    messages = []
    monkeypatch.setattr(recovery, "send_account_email", lambda email, purpose, token: messages.append((email,purpose,token)))
    return configure_local_services, TestClient(app), messages


def test_reset_changes_password_and_revokes_all_sessions(accounts):
    config, client, messages = accounts
    client.post("/auth/forgot-password",json={"email":config["user"].email})
    token = messages[0][2]
    second_token,_ = create_session(config["store"],config["user"])
    assert client.post("/auth/reset-password",json={"token":token,"password":"NewPassword2"}).status_code == 200
    for session in [config["token"],second_token]:
        assert client.get("/auth/me",headers={"Authorization":"Bearer "+session}).status_code == 401
    assert client.post("/auth/login",json={"email":config["user"].email,"password":"TestPassword1"}).status_code == 401
    assert client.post("/auth/login",json={"email":config["user"].email,"password":"NewPassword2"}).status_code == 200
    assert client.post("/auth/reset-password",json={"token":token,"password":"OtherPassword3"}).status_code == 400


def test_requests_do_not_expose_account_existence_or_tokens(accounts):
    config, client, messages = accounts
    known=client.post("/auth/forgot-password",json={"email":config["user"].email})
    missing=client.post("/auth/forgot-password",json={"email":"missing@example.com"})
    assert known.json() == missing.json()
    token=messages[0][2]
    assert token not in known.text
    with config["store"]._connect() as db:
        row=db.execute("SELECT token_hash FROM account_actions").fetchone()
    assert row[0] == hashlib.sha256(token.encode()).hexdigest()


def test_invalid_expired_wrong_purpose_links_do_not_change_password(accounts):
    config, client, _ = accounts
    actions=recovery.AccountActions(config["store"])
    token=actions.issue(config["user"],"verify")
    assert client.post("/auth/reset-password",json={"token":token,"password":"NewPassword2"}).status_code == 400
    with config["store"]._connect() as db:
        db.execute("UPDATE account_actions SET expires_at=?",((datetime.now(UTC)-timedelta(seconds=1)).isoformat(),))
    assert client.post("/auth/verify-email",json={"token":token}).status_code == 400
    assert client.post("/auth/reset-password",json={"token":"x"*43,"password":"NewPassword2"}).status_code == 400
    assert password_matches("TestPassword1",config["store"].get_user_by_email(config["user"].email))


def test_weak_password_does_not_consume_reset_link(accounts):
    config, client, _ = accounts
    token=recovery.AccountActions(config["store"]).issue(config["user"],"reset")
    assert client.post("/auth/reset-password",json={"token":token,"password":"alllowercase"}).status_code == 422
    assert client.post("/auth/reset-password",json={"token":token,"password":"NewPassword2"}).status_code == 200


def test_verification_is_optional_and_single_use(accounts):
    config, client, messages=accounts
    headers={"Authorization":"Bearer "+config["token"]}
    assert client.get("/materials",headers=headers).status_code == 200
    assert client.post("/auth/send-verification").status_code == 401
    assert client.post("/auth/send-verification",headers=headers).status_code == 200
    token=messages[0][2]
    assert client.post("/auth/verify-email",json={"token":token}).status_code == 200
    assert client.get("/auth/me",headers=headers).json()["email_verified"] is True
    assert client.post("/auth/verify-email",json={"token":token}).status_code == 400
    assert client.get("/materials",headers=headers).status_code == 200


def test_resend_has_per_account_cooldown(accounts):
    config,client,messages=accounts
    for _ in range(2): client.post("/auth/forgot-password",json={"email":config["user"].email})
    assert len(messages)==1


def test_only_one_concurrent_reset_can_consume_link(accounts):
    config,_,_=accounts
    actions=recovery.AccountActions(config["store"])
    token=actions.issue(config["user"],"reset")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _: actions.consume(token,"reset","NewPassword2"),range(2)))
    assert sorted(results)==[False,True]


def test_mail_failure_does_not_break_registration(accounts,monkeypatch):
    _,client,_=accounts
    def fail(*_): raise MailUnavailableError("Unavailable")
    monkeypatch.setattr(recovery,"send_account_email",fail)
    r=client.post("/auth/register",json={"email":"new@example.com","display_name":"New User","password":"NewPassword2"})
    assert r.status_code==200
    assert client.get("/auth/me",headers={"Authorization":"Bearer "+r.json()["token"]}).status_code==200


def test_preview_is_local_only_and_saves_private_message(accounts,tmp_path,monkeypatch):
    from backend import config
    monkeypatch.setattr(config,"DATABASE_PATH",tmp_path/"learnflow.db")
    send_account_email("test@example.com","reset","sample-token")
    files=list((tmp_path/"mail-preview").glob("*.eml"))
    assert len(files)==1
    assert "#reset-password?token=sample-token" in BytesParser(policy=policy.default).parsebytes(files[0].read_bytes()).get_content()
    monkeypatch.setenv("APP_ENV","production")
    with pytest.raises(MailUnavailableError): send_account_email("test@example.com","reset","sample-token")


def test_disabled_account_cannot_consume_issued_link(accounts):
    config,_,_=accounts
    actions=recovery.AccountActions(config["store"]);token=actions.issue(config["user"],"reset")
    with config["store"]._connect() as db: db.execute("UPDATE users SET disabled=1 WHERE user_id=?",(config["user"].user_id,))
    assert actions.consume(token,"reset","NewPassword2") is False


def test_old_database_migration_preserves_user_and_session(accounts):
    config,_,_=accounts
    store=config["store"]
    with store._connect() as db: db.execute("ALTER TABLE users DROP COLUMN email_verified")
    reopened=ResourceStore(store.database_path)
    user=reopened.get_user_by_email(config["user"].email)
    assert user.user_id==config["user"].user_id
    assert user.email_verified is False
    assert reopened.resolve_auth_session(hashlib.sha256(config["token"].encode()).hexdigest()).user_id==user.user_id
