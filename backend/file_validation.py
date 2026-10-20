"""Lightweight signature and container validation for local material uploads.

Not antivirus scanning or complete media decoding. File types are checked before
the API marks upload successful. Existing extraction is unchanged.
"""
from pathlib import Path
from zipfile import ZipFile, BadZipFile
import pymupdf
from PIL import Image

from .image_utils import InvalidImageError, load_rgb_image


def validate_upload_content(path: Path, extension: str) -> None:
    with path.open("rb") as stream:
        header = stream.read(4096)
    if not header:
        raise ValueError("Uploaded file is empty.")

    if extension == ".pdf":
        if not header.startswith(b"%PDF-"):
            raise ValueError("Invalid PDF signature.")
        try:
            with pymupdf.open(path) as doc:
                if not doc.page_count or doc.needs_pass:
                    raise ValueError("PDF is empty or password protected.")
        except (pymupdf.EmptyFileError, pymupdf.FileDataError) as exc:
            raise ValueError("PDF is corrupt.") from exc
    elif extension == ".pptx":
        if not header.startswith(b"PK"):
            raise ValueError("Invalid PPTX signature.")
        try:
            with ZipFile(path) as archive:
                names = set(archive.namelist())
                if not {"[Content_Types].xml", "ppt/presentation.xml"}.issubset(names):
                    raise ValueError("Invalid PPTX container contents.")
                for info in archive.infolist():
                    if info.file_size > 100 * 1024 * 1024:
                        raise ValueError("PPTX archive member exceeds safe size limit.")
        except BadZipFile as exc:
            raise ValueError("Corrupt PPTX archive.") from exc
    elif extension in {".png", ".jpg", ".jpeg"}:
        try:
            image = load_rgb_image(path)
        except InvalidImageError as exc:
            raise ValueError(str(exc)) from exc
        expected = "PNG" if extension == ".png" else "JPEG"
        with Image.open(path) as source:
            actual = source.format
        image.close()
        if actual != expected:
            raise ValueError(f"Image contents do not match the {extension} extension.")
    else:
        raise ValueError("Unsupported content type.")
