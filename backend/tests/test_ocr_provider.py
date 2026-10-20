"""Google OCR transport, billing guard, and explicit fallback tests."""

import base64
import json
from io import BytesIO

import httpx
from PIL import Image
import pytest

from backend.ocr import (
    FallbackOCRReader,
    GOOGLE_OCR_PROVIDER_KEY,
    GoogleDocumentAIOCRReader,
    OCRUnavailableError,
)
from backend.resource_store import ResourceStore


def png_bytes() -> bytes:
    stream = BytesIO()
    Image.new("RGB", (120, 60), "white").save(stream, format="PNG")
    return stream.getvalue()


def test_google_ocr_sends_inline_content_and_records_usage(monkeypatch, tmp_path):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = json.loads(request.content)
        assert payload["rawDocument"]["mimeType"] == "image/png"
        assert base64.b64decode(payload["rawDocument"]["content"]).startswith(
            b"\x89PNG"
        )
        assert payload["fieldMask"] == "text"
        return httpx.Response(200, json={"document": {"text": "Cloud OCR text"}})

    store = ResourceStore(tmp_path / "learnflow.db")
    reader = GoogleDocumentAIOCRReader(
        store,
        project_id="learnflow-project",
        location="us",
        processor_id="abc123",
        monthly_page_limit=2,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(reader, "_get_access_token", lambda: "test-token")

    assert reader.read_text(png_bytes()) == "Cloud OCR text"
    assert requests[0].headers["authorization"] == "Bearer test-token"
    assert requests[0].url.path.endswith("/processors/abc123:process")
    assert store.current_monthly_usage(GOOGLE_OCR_PROVIDER_KEY)[1] == 1


def test_google_ocr_stops_before_second_request_at_local_limit(monkeypatch, tmp_path):
    request_count = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(200, json={"document": {"text": "Text"}})

    reader = GoogleDocumentAIOCRReader(
        ResourceStore(tmp_path / "learnflow.db"),
        project_id="learnflow-project",
        location="us",
        processor_id="abc123",
        monthly_page_limit=1,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(reader, "_get_access_token", lambda: "test-token")

    assert reader.read_text(png_bytes()) == "Text"
    with pytest.raises(OCRUnavailableError, match="1-page monthly OCR limit"):
        reader.read_text(png_bytes())
    assert request_count == 1


def test_local_fallback_runs_only_after_cloud_failure():
    class FailingCloud:
        def read_text(self, _image):
            raise OCRUnavailableError("cloud unavailable")

    class LocalReader:
        def read_text(self, _image):
            return "Local fallback text"

    reader = FallbackOCRReader(FailingCloud(), LocalReader())

    assert reader.read_text(png_bytes()) == "Local fallback text"
