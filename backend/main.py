import os
import asyncio
from functools import lru_cache
import hashlib
import re
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from .chat_api import router as chat_router
from .extraction import extract_image, extract_pdf, extract_pptx
from .file_validation import validate_upload_content
from .observability import request_logging_middleware
from .ocr import OCRUnavailableError, get_ocr_reader
from .resource_store import ResourceRecord, ResourceStore, ResourceStoreError


app = FastAPI(title="LearnFlow AI API")
app.middleware("http")(request_logging_middleware)
app.include_router(chat_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("LEARNFLOW_CORS_ORIGINS", "http://localhost:5173").split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path(__file__).parent / "uploads"
DATABASE_PATH = Path(
    os.getenv(
        "LEARNFLOW_DATABASE_PATH",
        str(Path(__file__).parent / "data" / "learnflow.db"),
    )
)
MAX_UPLOAD_SIZE_MB = int(os.getenv("LEARNFLOW_MAX_UPLOAD_SIZE_MB", "100"))
MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024
EXTRACTION_TIMEOUT_SECONDS = int(os.getenv("LEARNFLOW_EXTRACTION_TIMEOUT_SECONDS", "180"))
EXTRACTION_PIPELINE_VERSION = "native-rapidocr-v1"
DOCUMENT_ID_PATTERN = re.compile(r"^[0-9a-f]{32}\.(pdf|pptx|png|jpe?g)$")
RESOURCE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
ALLOWED_EXTENSIONS = {
    ".pdf",
    ".pptx",
    ".png",
    ".jpg",
    ".jpeg",
}


@lru_cache(maxsize=1)
def get_resource_store() -> ResourceStore:
    return ResourceStore(DATABASE_PATH)


def source_type_for(extension: str) -> str:
    return {
        ".pdf": "pdf",
        ".pptx": "pptx",
        ".png": "image",
        ".jpg": "image",
        ".jpeg": "image",
    }[extension]


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def material_payload(
    record: ResourceRecord,
    *,
    filename: str | None = None,
    deduplicated: bool = False,
) -> dict[str, object]:
    return {
        "message": (
            "Existing material reused; processing will not be repeated."
            if deduplicated
            else "Material uploaded successfully."
        ),
        "resource_id": record.resource_id,
        "filename": filename or record.original_filename,
        "stored_filename": record.stored_filename,
        "size": record.size_bytes,
        "type": record.extension.removeprefix("."),
        "source_type": record.source_type,
        "status": record.status,
        "deduplicated": deduplicated,
    }


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


def get_uploaded_file(document_id: str) -> tuple[Path, str]:
    normalized_id = document_id.lower()
    match = DOCUMENT_ID_PATTERN.fullmatch(normalized_id)
    if not match:
        raise HTTPException(status_code=400, detail="Invalid document identifier.")

    extension = f".{match.group(1)}"
    upload_directory = UPLOAD_DIR.resolve()
    candidate = (upload_directory / normalized_id).resolve()
    if candidate.parent != upload_directory or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Uploaded material was not found.")

    return candidate, extension


@app.post("/materials/upload")
async def upload_material(file: UploadFile = File(...)) -> dict[str, object]:
    original_name = Path(file.filename or "").name
    extension = Path(original_name).suffix.lower()

    if not original_name or extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail="Unsupported file type. Please upload a PDF, PPTX, PNG, JPG, or JPEG file.",
        )

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    resource_id = uuid.uuid4().hex
    stored_name = f"{resource_id}{extension}"
    destination = UPLOAD_DIR / stored_name
    total_size = 0
    digest = hashlib.sha256()

    try:
        with destination.open("wb") as output_file:
            while chunk := await file.read(1024 * 1024):
                total_size += len(chunk)
                if total_size > MAX_UPLOAD_SIZE_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File is too large. The maximum size is {MAX_UPLOAD_SIZE_MB} MB.",
                    )
                digest.update(chunk)
                output_file.write(chunk)
        if total_size == 0:
            raise HTTPException(status_code=422, detail="Uploaded file is empty.")
        try:
            await run_in_threadpool(validate_upload_content, destination, extension)
        except ValueError as error:
            raise HTTPException(status_code=415, detail=str(error)) from error
        store = get_resource_store()
        content_hash = digest.hexdigest()
        existing = store.find_by_hash(content_hash)
        if existing is not None:
            existing_path = UPLOAD_DIR / existing.stored_filename
            if existing_path.is_file():
                destination.unlink(missing_ok=True)
                return material_payload(
                    existing, filename=original_name, deduplicated=True
                )
            store.delete(existing.resource_id)

        record, created = store.create(
            resource_id=resource_id,
            original_filename=original_name,
            stored_filename=stored_name,
            source_type=source_type_for(extension),
            extension=extension,
            content_hash=content_hash,
            size_bytes=total_size,
        )
        if not created:
            destination.unlink(missing_ok=True)
            return material_payload(
                record, filename=original_name, deduplicated=True
            )
    except HTTPException:
        destination.unlink(missing_ok=True)
        raise
    except OSError as error:
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=500,
            detail="The file could not be saved. Please try again.",
        ) from error
    except ResourceStoreError as error:
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=503,
            detail="Local resource metadata storage is unavailable.",
        ) from error
    finally:
        await file.close()

    return material_payload(record)


@app.get("/materials")
def list_materials() -> dict[str, list[dict[str, object]]]:
    try:
        records = get_resource_store().list()
    except ResourceStoreError as error:
        raise HTTPException(
            status_code=503, detail="Local resource metadata storage is unavailable."
        ) from error
    return {"materials": [record.public_dict() for record in records]}


@app.get("/materials/{resource_id}/status")
def material_status(resource_id: str) -> dict[str, object]:
    normalized_id = resource_id.lower()
    if not RESOURCE_ID_PATTERN.fullmatch(normalized_id):
        raise HTTPException(status_code=400, detail="Invalid resource identifier.")
    try:
        record = get_resource_store().get_by_resource_id(normalized_id)
    except ResourceStoreError as error:
        raise HTTPException(
            status_code=503, detail="Local resource metadata storage is unavailable."
        ) from error
    if record is None:
        raise HTTPException(status_code=404, detail="Resource was not found.")
    return record.public_dict()


@app.post("/materials/{document_id}/extract")
async def extract_material(document_id: str) -> dict[str, object]:
    path, extension = get_uploaded_file(document_id)

    try:
        store = get_resource_store()
        resource = store.get_by_stored_filename(path.name)
        if resource is None:
            resource, _ = store.create(
                resource_id=path.stem,
                original_filename=path.name,
                stored_filename=path.name,
                source_type=source_type_for(extension),
                extension=extension,
                content_hash=hash_file(path),
                size_bytes=path.stat().st_size,
            )
        cached_content = store.cached_extraction(
            resource.resource_id, EXTRACTION_PIPELINE_VERSION
        )
    except (OSError, ResourceStoreError) as error:
        raise HTTPException(
            status_code=503, detail="Local resource metadata storage is unavailable."
        ) from error

    if cached_content is not None:
        return {
            "document_id": path.name,
            "resource_id": resource.resource_id,
            "filename": path.name,
            "source_name": resource.original_filename,
            "extraction_status": "completed",
            "cached": True,
            "content": cached_content,
        }

    try:
        store.set_status(resource.resource_id, "processing")
    except ResourceStoreError as error:
        raise HTTPException(
            status_code=503, detail="Local resource metadata storage is unavailable."
        ) from error

    extractor = {
        ".pdf": extract_pdf,
        ".pptx": extract_pptx,
        ".png": extract_image,
        ".jpg": extract_image,
        ".jpeg": extract_image,
    }[extension]
    try:
        content = await asyncio.wait_for(
            run_in_threadpool(extractor, path, get_ocr_reader()),
            timeout=EXTRACTION_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as error:
        store.set_status(resource.resource_id, "failed", "Extraction timed out.")
        raise HTTPException(
            status_code=408,
            detail="Extraction took too long. Try a smaller document.",
        ) from error
    except (OSError, ValueError) as error:
        store.set_status(resource.resource_id, "failed", "Extraction failed.")
        raise HTTPException(
            status_code=422,
            detail=f"Could not extract text from this file: {error}",
        ) from error
    except OCRUnavailableError as error:
        store.set_status(resource.resource_id, "failed", "Local OCR is unavailable.")
        raise HTTPException(
            status_code=503,
            detail="Local OCR is unavailable. Install the backend OCR dependencies and retry.",
        ) from error
    except Exception as error:
        store.set_status(resource.resource_id, "failed", "Extraction failed.")
        raise HTTPException(
            status_code=422,
            detail="The material could not be processed.",
        ) from error

    if not any(item["has_text"] for item in content):
        unit_name = {".pdf": "pages", ".pptx": "slides"}.get(extension, "image")
        store.set_status(resource.resource_id, "failed", "No readable text was found.")
        raise HTTPException(
            status_code=422,
            detail=f"No readable text was found in this material's {unit_name} after text extraction and OCR.",
        )

    try:
        store.save_extraction(
            resource.resource_id, content, EXTRACTION_PIPELINE_VERSION
        )
    except ResourceStoreError as error:
        raise HTTPException(
            status_code=503, detail="Extracted content could not be cached locally."
        ) from error

    return {
        "document_id": path.name,
        "resource_id": resource.resource_id,
        "filename": path.name,
        "source_name": resource.original_filename,
        "extraction_status": "completed",
        "cached": False,
        "content": content,
    }
