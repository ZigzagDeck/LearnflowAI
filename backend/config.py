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
MAX_UPLOAD_SIZE_MB = int(os.getenv("LEARNFLOW_MAX_UPLOAD_SIZE_MB", "100"))
MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024
EXTRACTION_PIPELINE_VERSION = "native-rapidocr-v1"
CHUNKING_PIPELINE_VERSION = "semantic-boundary-v1"
PROCESSING_PIPELINE_VERSION = (
    f"{EXTRACTION_PIPELINE_VERSION}+{CHUNKING_PIPELINE_VERSION}"
)

