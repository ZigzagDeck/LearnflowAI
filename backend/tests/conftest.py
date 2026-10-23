"""Keep API tests isolated from the production SQLite registry."""
import pytest

from backend.auth import create_session, hash_password
from backend.resource_store import ResourceStore


@pytest.fixture(autouse=True)
def configure_local_services(monkeypatch, tmp_path_factory):
    monkeypatch.setenv("LEARNFLOW_EMAIL_MODE", "disabled")
    import backend.main as backend_main
    import backend.processing as backend_processing

    store = ResourceStore(tmp_path_factory.mktemp("registry") / "learnflow.db")
    password_hash, password_salt = hash_password("TestPassword1")
    user = store.create_user(
        email="test-user@example.com",
        display_name="Test User",
        password_hash=password_hash,
        password_salt=password_salt,
        role="user",
    )
    token, _ = create_session(store, user)
    monkeypatch.setattr(backend_main, "get_resource_store", lambda: store)
    monkeypatch.setattr(backend_main, "BEDROCK_CHAT_ENABLED", False)
    monkeypatch.setattr(backend_processing, "VISUAL_UNDERSTANDING_ENABLED", False)
    backend_main.app.state.resource_store = store
    if hasattr(backend_main.app.state, "chat_service"):
        del backend_main.app.state.chat_service
    return {"store": store, "user": user, "token": token}
