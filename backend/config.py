"""Environment-backed paths and processing limits shared by API and worker."""

import os
from pathlib import Path


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
EXTRACTION_PIPELINE_VERSION = "native-rapidocr-v1"
CHUNKING_PIPELINE_VERSION = "semantic-boundary-v1"
EMBEDDING_PIPELINE_VERSION = "fastembed-dense-v1"
PROCESSING_PIPELINE_VERSION = (
    f"{EXTRACTION_PIPELINE_VERSION}+{CHUNKING_PIPELINE_VERSION}"
    f"+{EMBEDDING_PIPELINE_VERSION}"
)

