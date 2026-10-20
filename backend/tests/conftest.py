"""Keep API tests isolated from the production SQLite registry."""
import pytest

from backend.resource_store import ResourceStore


@pytest.fixture(autouse=True)
def configure_local_services(monkeypatch, tmp_path_factory):
    import backend.main as backend_main

    store = ResourceStore(tmp_path_factory.mktemp("registry") / "learnflow.db")
    monkeypatch.setattr(backend_main, "get_resource_store", lambda: store)
