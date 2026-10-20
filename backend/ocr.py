"""Local OCR adapter with lazy model loading and no cloud dependency."""
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Protocol

from PIL import Image

from .image_utils import load_rgb_image


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
        try:
            with self._lock:
                result = self._get_engine()(decoded)
        except OCRUnavailableError:
            raise
        except Exception as exc:
            raise OCRUnavailableError("Local OCR could not process this image.") from exc

        texts = getattr(result, "txts", None) or ()
        scores = getattr(result, "scores", None) or ()
        accepted = []
        for index, value in enumerate(texts):
            text = str(value).strip()
            score = float(scores[index]) if index < len(scores) else 1.0
            if text and score >= 0.45:
                accepted.append(text)
        return "\n".join(accepted)


@lru_cache(maxsize=1)
def get_ocr_reader() -> OCRReader:
    return RapidOCRReader()
