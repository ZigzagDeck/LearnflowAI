"""Environment-backed paths and processing limits shared by API and worker."""

import os
from pathlib import Path

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).parent
load_dotenv(BACKEND_DIR.parent / ".env", override=False)


def _environment_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}

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
EMBEDDING_PROVIDER = os.getenv("LEARNFLOW_EMBEDDING_PROVIDER", "jina").strip()
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
JINA_API_KEY = os.getenv("JINA_API_KEY", "").strip()
JINA_EMBEDDING_MODEL = os.getenv(
    "LEARNFLOW_JINA_EMBEDDING_MODEL", "jina-embeddings-v3"
).strip()
JINA_EMBEDDING_DIMENSIONS = int(
    os.getenv("LEARNFLOW_JINA_EMBEDDING_DIMENSIONS", "256")
)
JINA_EMBEDDING_BATCH_SIZE = max(
    1, min(128, int(os.getenv("LEARNFLOW_JINA_EMBEDDING_BATCH_SIZE", "16")))
)
JINA_MONTHLY_TOKEN_LIMIT = max(
    1, int(os.getenv("LEARNFLOW_JINA_MONTHLY_TOKEN_LIMIT", "10000000"))
)
BEDROCK_CHAT_ENABLED = _environment_flag("LEARNFLOW_BEDROCK_CHAT_ENABLED")
BEDROCK_REGION = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1")).strip()
BEDROCK_MODEL_ID = os.getenv(
    "LEARNFLOW_BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0"
).strip()
BEDROCK_MAX_OUTPUT_TOKENS = max(
    64, min(2_000, int(os.getenv("LEARNFLOW_BEDROCK_MAX_OUTPUT_TOKENS", "600")))
)
BEDROCK_MONTHLY_TOKEN_UNIT_LIMIT = max(
    1,
    int(os.getenv("LEARNFLOW_BEDROCK_MONTHLY_TOKEN_UNIT_LIMIT", "2000000")),
)
YOUTUBE_TRANSCRIPT_LANGUAGES = tuple(
    language.strip()
    for language in os.getenv(
        "LEARNFLOW_YOUTUBE_TRANSCRIPT_LANGUAGES", "en,en-US,en-GB,hi"
    ).split(",")
    if language.strip()
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
EXTRACTION_PIPELINE_VERSION = (
    f"native-{OCR_PROVIDER}-selective-v2+youtube-captions-v1"
)
CHUNKING_PIPELINE_VERSION = "semantic-boundary-v1"
_embedding_version_name = (
    f"{JINA_EMBEDDING_MODEL}-{JINA_EMBEDDING_DIMENSIONS}"
    if EMBEDDING_PROVIDER == "jina"
    else EMBEDDING_MODEL_NAME.replace("/", "-")
)
EMBEDDING_PIPELINE_VERSION = (
    f"{EMBEDDING_PROVIDER}-{_embedding_version_name}-dense-v2"
)
PROCESSING_PIPELINE_VERSION = (
    f"{EXTRACTION_PIPELINE_VERSION}+{CHUNKING_PIPELINE_VERSION}"
    f"+{EMBEDDING_PIPELINE_VERSION}"
)

