import os
import asyncio
import re
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from .extraction import extract_pdf, extract_pptx
from .file_validation import validate_upload_content
from .observability import request_logging_middleware


app = FastAPI(title="LearnFlow AI API")
app.middleware("http")(request_logging_middleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("LEARNFLOW_CORS_ORIGINS", "http://localhost:5173").split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path(__file__).parent / "uploads"
MAX_UPLOAD_SIZE_MB = int(os.getenv("LEARNFLOW_MAX_UPLOAD_SIZE_MB", "100"))
MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024
EXTRACTION_TIMEOUT_SECONDS = 30
DOCUMENT_ID_PATTERN = re.compile(r"^[0-9a-f]{32}\.(pdf|ppt|pptx)$")
ALLOWED_EXTENSIONS = {
    ".pdf",
    ".ppt",
    ".pptx",
    ".mp4",
    ".webm",
    ".mov",
    ".avi",
    ".mkv",
}


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


def get_uploaded_file(document_id: str) -> tuple[Path, str]:
    match = DOCUMENT_ID_PATTERN.fullmatch(document_id.lower())
    if not match:
        raise HTTPException(status_code=400, detail="Invalid document identifier.")

    extension = f".{match.group(1)}"
    upload_directory = UPLOAD_DIR.resolve()
    candidate = (upload_directory / document_id).resolve()
    if candidate.parent != upload_directory or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Uploaded material was not found.")

    return candidate, extension


@app.post("/materials/upload")
async def upload_material(file: UploadFile = File(...)) -> dict[str, str | int]:
    original_name = Path(file.filename or "").name
    extension = Path(original_name).suffix.lower()

    if not original_name or extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail="Unsupported file type. Please upload a PDF, PPT, PPTX, MP4, WebM, MOV, AVI, or MKV file.",
        )

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{extension}"
    destination = UPLOAD_DIR / stored_name
    total_size = 0

    try:
        with destination.open("wb") as output_file:
            while chunk := await file.read(1024 * 1024):
                total_size += len(chunk)
                if total_size > MAX_UPLOAD_SIZE_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File is too large. The maximum size is {MAX_UPLOAD_SIZE_MB} MB.",
                    )
                output_file.write(chunk)
        if total_size == 0:
            raise HTTPException(status_code=422, detail="Uploaded file is empty.")
        try:
            await run_in_threadpool(validate_upload_content, destination, extension)
        except ValueError as error:
            raise HTTPException(status_code=415, detail=str(error)) from error
    except HTTPException:
        destination.unlink(missing_ok=True)
        raise
    except OSError as error:
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=500,
            detail="The file could not be saved. Please try again.",
        ) from error
    finally:
        await file.close()

    return {
        "message": "Material uploaded successfully.",
        "filename": original_name,
        "stored_filename": stored_name,
        "size": total_size,
        "type": extension.removeprefix("."),
    }


@app.post("/materials/{document_id}/extract")
async def extract_material(document_id: str) -> dict[str, str | list[dict[str, int | str | bool]]]:
    path, extension = get_uploaded_file(document_id)

    if extension == ".ppt":
        raise HTTPException(
            status_code=415,
            detail="Legacy .ppt files cannot be extracted with the current local extractor. Please convert the file to .pptx.",
        )

    extractor = extract_pdf if extension == ".pdf" else extract_pptx
    try:
        content = await asyncio.wait_for(
            run_in_threadpool(extractor, path),
            timeout=EXTRACTION_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as error:
        raise HTTPException(
            status_code=408,
            detail="Extraction took too long. Try a smaller document.",
        ) from error
    except (OSError, ValueError) as error:
        raise HTTPException(
            status_code=422,
            detail=f"Could not extract text from this file: {error}",
        ) from error
    except Exception as error:
        raise HTTPException(
            status_code=422,
            detail="The file could not be read as a valid PDF or PowerPoint presentation.",
        ) from error

    if not any(item["has_text"] for item in content):
        unit_name = "pages" if extension == ".pdf" else "slides"
        raise HTTPException(
            status_code=422,
            detail=f"No extractable text was found in this document's {unit_name}. Scanned PDFs may require OCR.",
        )

    return {
        "document_id": document_id,
        "filename": path.name,
        "extraction_status": "completed",
        "content": content,
    }
