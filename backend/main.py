import os
from contextlib import asynccontextmanager
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
from .chat_integration import build_local_bedrock_chat_service
from .quiz_api import router as quiz_router
from .quiz_integration import build_local_bedrock_quiz_service
from .contracts import YouTubeImportRequest
from .config import (
    CHUNKING_PIPELINE_VERSION,
    BEDROCK_API_MODE,
    BEDROCK_CHAT_ENABLED,
    BEDROCK_MODEL_ID,
    BEDROCK_MONTHLY_TOKEN_UNIT_LIMIT,
    DATABASE_PATH,
    EMBEDDING_PROVIDER,
    EXTRACTION_PIPELINE_VERSION,
    GOOGLE_DOCUMENT_AI_MONTHLY_PAGE_LIMIT,
    MAX_UPLOAD_SIZE_BYTES,
    MAX_UPLOAD_SIZE_MB,
    OCR_PROVIDER,
    OCR_LOCAL_ENGINE_ENABLED,
    OCR_LOCAL_FALLBACK_ENABLED,
    PROCESSING_PIPELINE_VERSION,
    UPLOAD_DIR,
    JINA_EMBEDDING_DIMENSIONS,
    JINA_EMBEDDING_MODEL,
    JINA_MONTHLY_TOKEN_LIMIT,
)
from .embeddings import JINA_USAGE_PROVIDER_KEY
from .file_validation import validate_upload_content
from .observability import request_logging_middleware
from .ocr import GOOGLE_OCR_PROVIDER_KEY
from .llm_provider import BEDROCK_USAGE_PROVIDER_KEY
from .resource_store import (
    ProcessingJob,
    ResourceProcessingError,
    ResourceRecord,
    ResourceStore,
    ResourceStoreError,
)
from .youtube_ingestion import parse_youtube_url


@asynccontextmanager
async def lifespan(application: FastAPI):
    store = get_resource_store()
    application.state.resource_store = store
    if BEDROCK_CHAT_ENABLED:
        application.state.chat_service = build_local_bedrock_chat_service(
            store
        )
        application.state.quiz_service = build_local_bedrock_quiz_service(store)
    yield


app = FastAPI(title="LearnFlow AI API", lifespan=lifespan)
app.middleware("http")(request_logging_middleware)
app.include_router(chat_router)
app.include_router(quiz_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("LEARNFLOW_CORS_ORIGINS", "http://localhost:5173").split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
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
        "source_url": record.source_url,
    }


def resource_payload(store: ResourceStore, record: ResourceRecord) -> dict[str, object]:
    payload = record.public_dict()
    job = store.get_extraction_job(record.resource_id)
    payload["processing_job"] = job.public_dict() if job else None
    return payload


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/usage/ocr")
def ocr_usage() -> dict[str, object]:
    try:
        period, used_pages = get_resource_store().current_monthly_usage(
            GOOGLE_OCR_PROVIDER_KEY
        )
    except ResourceStoreError as error:
        raise HTTPException(
            status_code=503, detail="OCR usage tracking is unavailable."
        ) from error
    return {
        "provider": OCR_PROVIDER,
        "execution": (
            "google_cloud" if OCR_PROVIDER == "google_document_ai" else "local"
        ),
        "local_engine_enabled": OCR_LOCAL_ENGINE_ENABLED,
        "local_fallback_enabled": (
            OCR_LOCAL_ENGINE_ENABLED and OCR_LOCAL_FALLBACK_ENABLED
        ),
        "period": period,
        "used_pages": used_pages,
        "monthly_page_limit": (
            GOOGLE_DOCUMENT_AI_MONTHLY_PAGE_LIMIT
            if OCR_PROVIDER == "google_document_ai"
            else None
        ),
    }


@app.get("/usage/embeddings")
def embedding_usage() -> dict[str, object]:
    try:
        period, used_units = get_resource_store().current_monthly_usage(
            JINA_USAGE_PROVIDER_KEY
        )
    except ResourceStoreError as error:
        raise HTTPException(
            status_code=503, detail="Embedding usage tracking is unavailable."
        ) from error
    return {
        "provider": EMBEDDING_PROVIDER,
        "model": JINA_EMBEDDING_MODEL if EMBEDDING_PROVIDER == "jina" else None,
        "dimensions": (
            JINA_EMBEDDING_DIMENSIONS if EMBEDDING_PROVIDER == "jina" else None
        ),
        "period": period,
        "used_conservative_token_units": used_units,
        "monthly_token_unit_limit": (
            JINA_MONTHLY_TOKEN_LIMIT if EMBEDDING_PROVIDER == "jina" else None
        ),
    }


@app.get("/usage/bedrock")
def bedrock_usage() -> dict[str, object]:
    try:
        period, used_units = get_resource_store().current_monthly_usage(
            BEDROCK_USAGE_PROVIDER_KEY
        )
    except ResourceStoreError as error:
        raise HTTPException(
            status_code=503, detail="Amazon Bedrock usage tracking is unavailable."
        ) from error
    return {
        "enabled": BEDROCK_CHAT_ENABLED,
        "api_mode": BEDROCK_API_MODE,
        "model": BEDROCK_MODEL_ID,
        "period": period,
        "used_conservative_token_units": used_units,
        "monthly_token_unit_limit": BEDROCK_MONTHLY_TOKEN_UNIT_LIMIT,
    }


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
                    existing.resource_id, PROCESSING_PIPELINE_VERSION
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
                record.resource_id, PROCESSING_PIPELINE_VERSION
            )
            return material_payload(
                record,
                job=job,
                filename=original_name,
                deduplicated=True,
            )
        job = store.enqueue_extraction(record.resource_id, PROCESSING_PIPELINE_VERSION)
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


@app.post("/materials/youtube")
def import_youtube_material(payload: YouTubeImportRequest) -> dict[str, object]:
    try:
        reference = parse_youtube_url(payload.url)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    content_hash = hashlib.sha256(reference.canonical_url.encode("utf-8")).hexdigest()
    try:
        store = get_resource_store()
        existing = store.find_by_hash(content_hash)
        if existing is not None:
            job = store.enqueue_extraction(
                existing.resource_id, PROCESSING_PIPELINE_VERSION
            )
            return material_payload(existing, job=job, deduplicated=True)

        resource_id = uuid.uuid4().hex
        record, _ = store.create(
            resource_id=resource_id,
            original_filename=f"YouTube video {reference.video_id}",
            stored_filename=f"youtube-{reference.video_id}",
            source_type="video",
            extension=".youtube",
            content_hash=content_hash,
            size_bytes=len(reference.canonical_url.encode("utf-8")),
            source_url=reference.canonical_url,
        )
        job = store.enqueue_extraction(record.resource_id, PROCESSING_PIPELINE_VERSION)
    except ResourceStoreError as error:
        raise HTTPException(
            status_code=503, detail="Local resource metadata storage is unavailable."
        ) from error
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


@app.delete("/materials/{resource_id}")
def delete_material(resource_id: str) -> dict[str, str]:
    normalized_id = resource_id.lower()
    if not RESOURCE_ID_PATTERN.fullmatch(normalized_id):
        raise HTTPException(status_code=400, detail="Invalid resource identifier.")
    try:
        store = get_resource_store()
        record = store.get_by_resource_id(normalized_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Resource was not found.")
        if not store.delete(normalized_id, reject_processing=True):
            raise HTTPException(
                status_code=404, detail="Resource was not found."
            )
    except ResourceProcessingError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ResourceStoreError as error:
        raise HTTPException(
            status_code=503, detail="Local resource data could not be deleted."
        ) from error

    if record.extension != ".youtube":
        upload_directory = UPLOAD_DIR.resolve()
        candidate = (upload_directory / record.stored_filename).resolve()
        if candidate.parent == upload_directory:
            try:
                candidate.unlink(missing_ok=True)
            except OSError:
                # The database row and its derived indexes are already removed.
                pass
    return {"resource_id": normalized_id, "status": "deleted"}


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
            normalized_id, PROCESSING_PIPELINE_VERSION, retry_failed=True
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


@app.get("/materials/{resource_id}/chunks")
def material_chunks(resource_id: str) -> dict[str, object]:
    normalized_id = resource_id.lower()
    if not RESOURCE_ID_PATTERN.fullmatch(normalized_id):
        raise HTTPException(status_code=400, detail="Invalid resource identifier.")
    try:
        store = get_resource_store()
        if store.get_by_resource_id(normalized_id) is None:
            raise HTTPException(status_code=404, detail="Resource was not found.")
        chunks = store.list_chunks(normalized_id, CHUNKING_PIPELINE_VERSION)
    except ResourceStoreError as error:
        raise HTTPException(
            status_code=503, detail="Normalized material chunks are unavailable."
        ) from error
    if not chunks:
        raise HTTPException(
            status_code=409, detail="Material chunking has not completed yet."
        )
    return {
        "resource_id": normalized_id,
        "chunk_version": CHUNKING_PIPELINE_VERSION,
        "chunks": [chunk.public_dict() for chunk in chunks],
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
            resource.resource_id, PROCESSING_PIPELINE_VERSION, retry_failed=True
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
