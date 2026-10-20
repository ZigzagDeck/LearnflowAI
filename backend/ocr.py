"""Configurable OCR providers with a cloud usage cap and local fallback."""

import base64
from functools import lru_cache
from io import BytesIO
import json
from pathlib import Path
import re
from threading import Lock
from typing import Protocol

import httpx
from PIL import Image

from .config import (
    DATABASE_PATH,
    GOOGLE_CLOUD_PROJECT,
    GOOGLE_DOCUMENT_AI_LOCATION,
    GOOGLE_DOCUMENT_AI_MONTHLY_PAGE_LIMIT,
    GOOGLE_DOCUMENT_AI_PROCESSOR_ID,
    GOOGLE_SERVICE_ACCOUNT_JSON,
    OCR_LOCAL_FALLBACK_ENABLED,
    OCR_PROVIDER,
)
from .image_utils import load_rgb_image
from .resource_store import (
    MonthlyUsageLimitError,
    ResourceStore,
    ResourceStoreError,
)


GOOGLE_OCR_PROVIDER_KEY = "google_document_ai_ocr"
MAX_INLINE_DOCUMENT_BYTES = 35 * 1024 * 1024
GOOGLE_AUTH_SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)


class OCRUnavailableError(RuntimeError):
    """The configured OCR engine is unavailable."""


class OCRReader(Protocol):
    def read_text(self, image: Path | bytes | Image.Image) -> str: ...


class RapidOCRReader:
    """Reuse one CPU OCR model while serializing inference for thread safety."""

    def __init__(self) -> None:
        self._engine = None
        self._lock = Lock()

    def _get_engine(self):
        if self._engine is None:
            try:
                from rapidocr import RapidOCR
            except ImportError as exc:
                raise OCRUnavailableError(
                    "Local OCR dependencies are not installed."
                ) from exc
            self._engine = RapidOCR()
        return self._engine

    def read_text(self, image: Path | bytes | Image.Image) -> str:
        decoded = image if isinstance(image, Image.Image) else load_rgb_image(image)
        should_close = not isinstance(image, Image.Image)
        try:
            with self._lock:
                result = self._get_engine()(decoded)
        except OCRUnavailableError:
            raise
        except Exception as exc:
            raise OCRUnavailableError("Local OCR could not process this image.") from exc
        finally:
            if should_close:
                decoded.close()

        texts = getattr(result, "txts", None) or ()
        scores = getattr(result, "scores", None) or ()
        accepted = []
        for index, value in enumerate(texts):
            text = str(value).strip()
            score = float(scores[index]) if index < len(scores) else 1.0
            if text and score >= 0.45:
                accepted.append(text)
        return "\n".join(accepted)


class GoogleDocumentAIOCRReader:
    """Send bounded inline images to Enterprise Document OCR without Cloud Storage."""

    def __init__(
        self,
        store: ResourceStore,
        *,
        project_id: str = GOOGLE_CLOUD_PROJECT,
        location: str = GOOGLE_DOCUMENT_AI_LOCATION,
        processor_id: str = GOOGLE_DOCUMENT_AI_PROCESSOR_ID,
        monthly_page_limit: int = GOOGLE_DOCUMENT_AI_MONTHLY_PAGE_LIMIT,
        service_account_json: str = GOOGLE_SERVICE_ACCOUNT_JSON,
        client: httpx.Client | None = None,
    ) -> None:
        self.store = store
        self.project_id = project_id
        self.location = location
        self.processor_id = processor_id
        self.monthly_page_limit = monthly_page_limit
        self.service_account_json = service_account_json
        self._client = client or httpx.Client(timeout=60.0)
        self._credentials = None
        self._lock = Lock()

    def _get_access_token(self) -> str:
        try:
            import google.auth
            from google.auth.transport.requests import Request
            from google.oauth2 import service_account

            if self._credentials is None:
                if self.service_account_json:
                    info = json.loads(self.service_account_json)
                    self._credentials = service_account.Credentials.from_service_account_info(
                        info, scopes=GOOGLE_AUTH_SCOPES
                    )
                    self.project_id = self.project_id or str(info.get("project_id", ""))
                else:
                    self._credentials, detected_project = google.auth.default(
                        scopes=GOOGLE_AUTH_SCOPES
                    )
                    self.project_id = self.project_id or str(detected_project or "")
            if not self._credentials.valid or self._credentials.expired:
                self._credentials.refresh(Request())
            token = self._credentials.token
            if not token:
                raise ValueError("Google credentials returned no access token.")
            return str(token)
        except Exception as exc:
            raise OCRUnavailableError(
                "Google Document AI credentials are missing or invalid."
            ) from exc

    @staticmethod
    def _encode_image(image: Path | bytes | Image.Image) -> tuple[bytes, str]:
        decoded = image if isinstance(image, Image.Image) else load_rgb_image(image)
        should_close = not isinstance(image, Image.Image)
        try:
            stream = BytesIO()
            decoded.save(stream, format="PNG")
            content = stream.getvalue()
            mime_type = "image/png"
            if len(content) > MAX_INLINE_DOCUMENT_BYTES:
                stream = BytesIO()
                decoded.convert("RGB").save(stream, format="JPEG", quality=88)
                content = stream.getvalue()
                mime_type = "image/jpeg"
            if len(content) > MAX_INLINE_DOCUMENT_BYTES:
                raise OCRUnavailableError(
                    "This rendered page is too large for inline Google OCR."
                )
            return content, mime_type
        finally:
            if should_close:
                decoded.close()

    def _endpoint(self) -> str:
        if not re.fullmatch(r"[a-z0-9-]{1,63}", self.project_id):
            raise OCRUnavailableError("GOOGLE_CLOUD_PROJECT is not configured.")
        if not re.fullmatch(r"[a-z0-9-]{1,40}", self.location):
            raise OCRUnavailableError("GOOGLE_DOCUMENT_AI_LOCATION is invalid.")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", self.processor_id):
            raise OCRUnavailableError(
                "GOOGLE_DOCUMENT_AI_PROCESSOR_ID is not configured."
            )
        return (
            f"https://{self.location}-documentai.googleapis.com/v1/"
            f"projects/{self.project_id}/locations/{self.location}/"
            f"processors/{self.processor_id}:process"
        )

    def read_text(self, image: Path | bytes | Image.Image) -> str:
        content, mime_type = self._encode_image(image)
        with self._lock:
            try:
                token = self._get_access_token()
                endpoint = self._endpoint()
                self.store.reserve_monthly_usage(
                    GOOGLE_OCR_PROVIDER_KEY, 1, self.monthly_page_limit
                )
                response = self._client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "rawDocument": {
                            "mimeType": mime_type,
                            "content": base64.b64encode(content).decode("ascii"),
                        },
                        "fieldMask": "text",
                    },
                )
                response.raise_for_status()
                payload = response.json()
            except MonthlyUsageLimitError as exc:
                raise OCRUnavailableError(
                    f"The configured {self.monthly_page_limit}-page monthly OCR "
                    "limit has been reached."
                ) from exc
            except ResourceStoreError as exc:
                raise OCRUnavailableError(
                    "Google OCR usage tracking is unavailable; no request was sent."
                ) from exc
            except httpx.HTTPStatusError as exc:
                raise OCRUnavailableError(
                    "Google Document AI rejected the OCR request "
                    f"with status {exc.response.status_code}."
                ) from exc
            except (httpx.HTTPError, ValueError) as exc:
                raise OCRUnavailableError(
                    "Google Document AI could not process this page."
                ) from exc
        if not isinstance(payload, dict):
            raise OCRUnavailableError("Google Document AI returned an invalid response.")
        document = payload.get("document")
        if not isinstance(document, dict):
            raise OCRUnavailableError("Google Document AI returned an invalid response.")
        return str(document.get("text") or "").strip()


class FallbackOCRReader:
    def __init__(self, primary: OCRReader, fallback: OCRReader):
        self.primary = primary
        self.fallback = fallback

    def read_text(self, image: Path | bytes | Image.Image) -> str:
        try:
            return self.primary.read_text(image)
        except OCRUnavailableError:
            return self.fallback.read_text(image)


@lru_cache(maxsize=1)
def get_ocr_reader() -> OCRReader:
    if OCR_PROVIDER == "rapidocr":
        return RapidOCRReader()
    if OCR_PROVIDER != "google_document_ai":
        raise OCRUnavailableError(
            "LEARNFLOW_OCR_PROVIDER must be google_document_ai or rapidocr."
        )
    primary = GoogleDocumentAIOCRReader(ResourceStore(DATABASE_PATH))
    if OCR_LOCAL_FALLBACK_ENABLED:
        return FallbackOCRReader(primary, RapidOCRReader())
    return primary
