"""Account email delivery; preview messages stay outside the public web root."""
import os
from email.message import EmailMessage
import smtplib
import ssl
import uuid
from urllib.parse import urlsplit


class MailUnavailableError(RuntimeError):
    pass


def mail_settings() -> tuple[str, str]:
    mode = os.getenv("LEARNFLOW_EMAIL_MODE", "disabled").strip()
    base = os.getenv("LEARNFLOW_PUBLIC_APP_URL", "http://localhost:5173").rstrip("/")
    url = urlsplit(base)
    if url.query or url.fragment or url.username or not url.hostname:
        raise MailUnavailableError("Account email configuration is invalid.")
    if mode == "preview":
        if os.getenv("APP_ENV") != "development" or url.hostname not in {"localhost", "127.0.0.1"}:
            raise MailUnavailableError("Email preview is restricted to local development.")
    elif mode == "smtp":
        if url.scheme != "https" and url.hostname not in {"localhost", "127.0.0.1"}:
            raise MailUnavailableError("Account links require HTTPS.")
        if not os.getenv("LEARNFLOW_SMTP_HOST") or not os.getenv("LEARNFLOW_EMAIL_FROM"):
            raise MailUnavailableError("Email delivery is not configured.")
    else:
        raise MailUnavailableError("Email delivery is not configured. Please contact the administrator.")
    return mode, base


def send_account_email(recipient: str, purpose: str, token: str) -> None:
    mode, base = mail_settings()
    action = "reset-password" if purpose == "reset" else "verify-email"
    minutes = "30 minutes" if purpose == "reset" else "24 hours"
    subject = "Reset your LearnFlow password" if purpose == "reset" else "Verify your LearnFlow email"
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = (os.getenv("LEARNFLOW_EMAIL_FROM") or "LearnFlow <no-reply@localhost>")
    message["To"] = recipient
    message.set_content(f"{subject}\n\n{base}/#{action}?token={token}\n\nThis link expires in {minutes} and can be used once. If you did not request it, ignore this email.")
    if mode == "preview":
        from .config import DATABASE_PATH
        folder = DATABASE_PATH.parent / "mail-preview"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{uuid.uuid4().hex}.eml").write_bytes(message.as_bytes())
        return
    try:
        host = os.environ["LEARNFLOW_SMTP_HOST"]
        port = int(os.getenv("LEARNFLOW_SMTP_PORT", "587"))
        implicit_tls = os.getenv("LEARNFLOW_SMTP_SSL", "false").lower() == "true"
        client = smtplib.SMTP_SSL(host, port, timeout=15, context=ssl.create_default_context()) if implicit_tls else smtplib.SMTP(host, port, timeout=15)
        with client:
            if not implicit_tls:
                client.starttls(context=ssl.create_default_context())
            username = os.getenv("LEARNFLOW_SMTP_USERNAME", "")
            if username:
                client.login(username, os.getenv("LEARNFLOW_SMTP_PASSWORD", ""))
            client.send_message(message)
    except Exception as exc:
        raise MailUnavailableError("Email delivery is temporarily unavailable.") from exc
