import os
from functools import lru_cache
import hashlib
import re
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .chat_api import router as chat_router
from .config import (
    DATABASE_PATH,
    EXTRACTION_PIPELINE_VERSION,
    MAX_UPLOAD_SIZE_BYTES,
    MAX_UPLOAD_SIZE_MB,
    UPLOAD_DIR,
)
from .file_validation import validate_upload_content
from .observability import request_logging_middleware
from .resource_store import (
    ProcessingJob,
    ResourceRecord,
    ResourceStore,
    ResourceStoreError,
)


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
    job: ProcessingJob | None = None,
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
        "processing_job": job.public_dict() if job else None,
    }


def resource_payload(store: ResourceStore, record: ResourceRecord) -> dict[str, object]:
    payload = record.public_dict()
    job = store.get_extraction_job(record.resource_id)
    payload["processing_job"] = job.public_dict() if job else None
    return payload


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
                job = store.enqueue_extraction(
                    existing.resource_id, EXTRACTION_PIPELINE_VERSION
                )
                return material_payload(
                    existing,
                    job=job,
                    filename=original_name,
                    deduplicated=True,
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
            job = store.enqueue_extraction(
                record.resource_id, EXTRACTION_PIPELINE_VERSION
            )
            return material_payload(
                record,
                job=job,
                filename=original_name,
                deduplicated=True,
            )
        job = store.enqueue_extraction(record.resource_id, EXTRACTION_PIPELINE_VERSION)
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

    return material_payload(record, job=job)


@app.get("/materials")
def list_materials() -> dict[str, list[dict[str, object]]]:
    try:
        store = get_resource_store()
        records = store.list()
    except ResourceStoreError as error:
        raise HTTPException(
            status_code=503, detail="Local resource metadata storage is unavailable."
        ) from error
    return {"materials": [resource_payload(store, record) for record in records]}


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
    return resource_payload(get_resource_store(), record)


@app.post("/materials/{resource_id}/process")
def queue_material_processing(resource_id: str) -> dict[str, object]:
    normalized_id = resource_id.lower()
    if not RESOURCE_ID_PATTERN.fullmatch(normalized_id):
        raise HTTPException(status_code=400, detail="Invalid resource identifier.")
    try:
        store = get_resource_store()
        record = store.get_by_resource_id(normalized_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Resource was not found.")
        job = store.enqueue_extraction(
            normalized_id, EXTRACTION_PIPELINE_VERSION, retry_failed=True
        )
        record = store.get_by_resource_id(normalized_id)
    except ResourceStoreError as error:
        raise HTTPException(
            status_code=503, detail="Local processing queue is unavailable."
        ) from error
    return {
        "resource_id": normalized_id,
        "status": record.status if record else "uploaded",
        "processing_job": job.public_dict(),
    }


@app.get("/materials/{resource_id}/content")
def material_content(resource_id: str) -> dict[str, object]:
    normalized_id = resource_id.lower()
    if not RESOURCE_ID_PATTERN.fullmatch(normalized_id):
        raise HTTPException(status_code=400, detail="Invalid resource identifier.")
    try:
        store = get_resource_store()
        record = store.get_by_resource_id(normalized_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Resource was not found.")
        content = store.cached_extraction(normalized_id, EXTRACTION_PIPELINE_VERSION)
    except ResourceStoreError as error:
        raise HTTPException(
            status_code=503, detail="Extracted content is unavailable."
        ) from error
    if content is None:
        raise HTTPException(
            status_code=409,
            detail="Material processing has not completed yet.",
        )
    return {
        "resource_id": normalized_id,
        "source_name": record.original_filename,
        "extraction_status": "completed",
        "cached": True,
        "content": content,
    }


@app.post("/materials/{document_id}/extract")
def extract_material(document_id: str):
    """Compatibility route: queue work and return immediately, or return cache."""
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
        job = store.enqueue_extraction(
            resource.resource_id, EXTRACTION_PIPELINE_VERSION, retry_failed=True
        )
    except ResourceStoreError as error:
        raise HTTPException(
            status_code=503, detail="Local processing queue is unavailable."
        ) from error
    return JSONResponse(
        status_code=202,
        content={
            "document_id": path.name,
            "resource_id": resource.resource_id,
            "filename": path.name,
            "source_name": resource.original_filename,
            "extraction_status": job.status,
            "cached": False,
            "processing_job": job.public_dict(),
        },
    )
