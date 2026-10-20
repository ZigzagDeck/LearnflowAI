"""Safe image decoding shared by upload validation and local OCR."""
from io import BytesIO
from pathlib import Path
import warnings

from PIL import Image, UnidentifiedImageError


MAX_IMAGE_PIXELS = 40_000_000
SUPPORTED_IMAGE_FORMATS = {"JPEG", "PNG"}


class InvalidImageError(ValueError):
    """The uploaded or embedded image cannot be processed safely."""


def load_rgb_image(source: Path | bytes) -> Image.Image:
    """Decode a bounded JPEG/PNG and return an independent RGB image."""
    stream = source if isinstance(source, Path) else BytesIO(source)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(stream) as image:
                if image.format not in SUPPORTED_IMAGE_FORMATS:
                    raise InvalidImageError("Only PNG and JPEG images are supported.")
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise InvalidImageError(
                        f"Image dimensions are too large. The limit is {MAX_IMAGE_PIXELS:,} pixels."
                    )
                image.load()
                return image.convert("RGB")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
        raise InvalidImageError("Image is corrupt or cannot be decoded.") from exc
