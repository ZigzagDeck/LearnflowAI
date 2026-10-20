"""Environment-backed paths and processing limits shared by API and worker."""

import os
from pathlib import Path


def _environment_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


BACKEND_DIR = Path(__file__).parent
UPLOAD_DIR = Path(
    os.getenv("LEARNFLOW_UPLOAD_DIR", str(BACKEND_DIR / "uploads"))
)
DATABASE_PATH = Path(
    os.getenv("LEARNFLOW_DATABASE_PATH", str(BACKEND_DIR / "data" / "learnflow.db"))
)
MODEL_CACHE_DIR = Path(
    os.getenv("LEARNFLOW_MODEL_CACHE_DIR", str(BACKEND_DIR / "data" / "models"))
)
MAX_UPLOAD_SIZE_MB = int(os.getenv("LEARNFLOW_MAX_UPLOAD_SIZE_MB", "100"))
MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024
EMBEDDING_PROVIDER = os.getenv("LEARNFLOW_EMBEDDING_PROVIDER", "voyage").strip()
EMBEDDING_LOCAL_FALLBACK_ENABLED = _environment_flag(
    "LEARNFLOW_EMBEDDING_LOCAL_FALLBACK_ENABLED"
)
EMBEDDING_MODEL_NAME = os.getenv(
    "LEARNFLOW_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"
)
EMBEDDING_THREADS = max(1, min(2, int(os.getenv("LEARNFLOW_EMBEDDING_THREADS", "1"))))
EMBEDDING_BATCH_SIZE = max(
    1, min(8, int(os.getenv("LEARNFLOW_EMBEDDING_BATCH_SIZE", "4")))
)
MIN_EMBEDDING_FREE_MB = max(
    256, int(os.getenv("LEARNFLOW_MIN_EMBEDDING_FREE_MB", "768"))
)
VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY", "").strip()
VOYAGE_EMBEDDING_MODEL = os.getenv(
    "LEARNFLOW_VOYAGE_EMBEDDING_MODEL", "voyage-4-lite"
).strip()
VOYAGE_EMBEDDING_DIMENSIONS = int(
    os.getenv("LEARNFLOW_VOYAGE_EMBEDDING_DIMENSIONS", "256")
)
VOYAGE_EMBEDDING_BATCH_SIZE = max(
    1, min(128, int(os.getenv("LEARNFLOW_VOYAGE_EMBEDDING_BATCH_SIZE", "32")))
)
VOYAGE_MONTHLY_TOKEN_LIMIT = max(
    1, int(os.getenv("LEARNFLOW_VOYAGE_MONTHLY_TOKEN_LIMIT", "10000000"))
)
OCR_PROVIDER = os.getenv("LEARNFLOW_OCR_PROVIDER", "google_document_ai").strip()
OCR_LOCAL_FALLBACK_ENABLED = _environment_flag(
    "LEARNFLOW_OCR_LOCAL_FALLBACK_ENABLED"
)
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
GOOGLE_DOCUMENT_AI_LOCATION = os.getenv(
    "GOOGLE_DOCUMENT_AI_LOCATION", "us"
).strip()
GOOGLE_DOCUMENT_AI_PROCESSOR_ID = os.getenv(
    "GOOGLE_DOCUMENT_AI_PROCESSOR_ID", ""
).strip()
GOOGLE_DOCUMENT_AI_MONTHLY_PAGE_LIMIT = max(
    1, int(os.getenv("LEARNFLOW_GOOGLE_OCR_MONTHLY_PAGE_LIMIT", "1000"))
)
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv(
    "LEARNFLOW_GOOGLE_SERVICE_ACCOUNT_JSON", ""
).strip()
EXTRACTION_PIPELINE_VERSION = f"native-{OCR_PROVIDER}-selective-v2"
CHUNKING_PIPELINE_VERSION = "semantic-boundary-v1"
_embedding_version_name = (
    f"{VOYAGE_EMBEDDING_MODEL}-{VOYAGE_EMBEDDING_DIMENSIONS}"
    if EMBEDDING_PROVIDER == "voyage"
    else EMBEDDING_MODEL_NAME.replace("/", "-")
)
EMBEDDING_PIPELINE_VERSION = (
    f"{EMBEDDING_PROVIDER}-{_embedding_version_name}-dense-v2"
)
PROCESSING_PIPELINE_VERSION = (
    f"{EXTRACTION_PIPELINE_VERSION}+{CHUNKING_PIPELINE_VERSION}"
    f"+{EMBEDDING_PIPELINE_VERSION}"
)

