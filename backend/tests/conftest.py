"""Keep API tests fast and deterministic while production uses local RapidOCR."""
import pytest

from backend.resource_store import ResourceStore


class EmptyOCR:
    def read_text(self, image) -> str:
        return ""


@pytest.fixture(autouse=True)
def configure_local_services(monkeypatch, tmp_path_factory):
    import backend.main as backend_main

    monkeypatch.setattr(backend_main, "get_ocr_reader", lambda: EmptyOCR())
    store = ResourceStore(tmp_path_factory.mktemp("registry") / "learnflow.db")
    monkeypatch.setattr(backend_main, "get_resource_store", lambda: store)
