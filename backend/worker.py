"""Command-line worker for restart-safe local OCR and text extraction."""

import logging
import os
import signal
import time

from .config import DATABASE_PATH, UPLOAD_DIR
from .processing import process_next_job
from .resource_store import ResourceStore, ResourceStoreError


LOGGER = logging.getLogger("learnflow.worker")
POLL_SECONDS = max(0.25, float(os.getenv("LEARNFLOW_WORKER_POLL_SECONDS", "1")))
STALE_SECONDS = max(60, int(os.getenv("LEARNFLOW_JOB_STALE_SECONDS", "900")))


def run_worker() -> None:
    logging.basicConfig(
        level=os.getenv("LEARNFLOW_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    store = ResourceStore(DATABASE_PATH)
    recovered = store.recover_interrupted_jobs(STALE_SECONDS)
    if recovered:
        LOGGER.info("Requeued %s interrupted processing job(s).", recovered)

    stopping = False

    def request_stop(_signum, _frame) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    LOGGER.info("Local extraction worker started; processing one job at a time.")

    while not stopping:
        try:
            job = process_next_job(store, UPLOAD_DIR)
            if job is None:
                recovered = store.recover_interrupted_jobs(STALE_SECONDS)
                if recovered:
                    LOGGER.info("Requeued %s interrupted processing job(s).", recovered)
                time.sleep(POLL_SECONDS)
            elif job.status == "completed":
                LOGGER.info("Completed processing job %s.", job.job_id)
            else:
                LOGGER.warning("Processing job %s failed: %s", job.job_id, job.error)
        except ResourceStoreError as error:
            LOGGER.error("Worker storage error: %s", error)
            time.sleep(POLL_SECONDS)

    LOGGER.info("Local extraction worker stopped.")


if __name__ == "__main__":
    run_worker()

