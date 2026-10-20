"""Durable, single-job local extraction processing."""

from collections.abc import Callable
from pathlib import Path

from .extraction import extract_image, extract_pdf, extract_pptx
from .ocr import OCRReader, OCRUnavailableError, get_ocr_reader
from .resource_store import ProcessingJob, ResourceStore, ResourceStoreError


SAFE_GENERIC_FAILURE = "The material could not be processed."


def process_next_job(
    store: ResourceStore,
    upload_dir: Path,
    *,
    ocr_factory: Callable[[], OCRReader] = get_ocr_reader,
) -> ProcessingJob | None:
    """Claim and complete at most one queued job in the calling process."""
    job = store.claim_next_extraction()
    if job is None:
        return None

    resource = store.get_by_resource_id(job.resource_id)
    if resource is None:
        store.fail_job(job.job_id, job.resource_id, "The uploaded material was not found.")
        return store.get_extraction_job(job.resource_id)

    cached = store.cached_extraction(resource.resource_id, job.pipeline_version)
    if cached is not None:
        store.complete_job(job.job_id)
        return store.get_extraction_job(job.resource_id)

    path = upload_dir / resource.stored_filename
    if not path.is_file():
        store.fail_job(job.job_id, job.resource_id, "The uploaded material file is missing.")
        return store.get_extraction_job(job.resource_id)

    extractor = {
        ".pdf": extract_pdf,
        ".pptx": extract_pptx,
        ".png": extract_image,
        ".jpg": extract_image,
        ".jpeg": extract_image,
    }.get(resource.extension)
    if extractor is None:
        store.fail_job(job.job_id, job.resource_id, "This material type is not supported.")
        return store.get_extraction_job(job.resource_id)

    def report_progress(current: int, total: int) -> None:
        store.update_job_progress(job.job_id, current, total)

    try:
        content = extractor(path, ocr_factory(), report_progress)
        if not any(item["has_text"] for item in content):
            unit_name = {".pdf": "pages", ".pptx": "slides"}.get(
                resource.extension, "image"
            )
            raise ValueError(
                f"No readable text was found in this material's {unit_name} "
                "after text extraction and OCR."
            )
        store.save_extraction(
            resource.resource_id, content, job.pipeline_version
        )
        store.complete_job(job.job_id)
    except OCRUnavailableError:
        store.fail_job(
            job.job_id,
            job.resource_id,
            "Local OCR is unavailable. Install the backend OCR dependencies and retry.",
        )
    except (OSError, ValueError) as error:
        store.fail_job(job.job_id, job.resource_id, str(error))
    except ResourceStoreError:
        raise
    except Exception:
        store.fail_job(job.job_id, job.resource_id, SAFE_GENERIC_FAILURE)

    return store.get_extraction_job(job.resource_id)

