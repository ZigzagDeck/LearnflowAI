"""Keep API tests fast and deterministic while production uses local RapidOCR."""
import pytest


class EmptyOCR:
    def read_text(self, image) -> str:
        return ""


@pytest.fixture(autouse=True)
def stub_default_ocr(monkeypatch):
    import backend.main as backend_main

    monkeypatch.setattr(backend_main, "get_ocr_reader", lambda: EmptyOCR())
