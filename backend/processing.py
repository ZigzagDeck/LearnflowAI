"""Durable, single-job local extraction processing."""

from collections.abc import Callable
from pathlib import Path

from .chunking import build_chunks
from .config import (
    CHUNKING_PIPELINE_VERSION,
    EXTRACTION_PIPELINE_VERSION,
    VISUAL_MAX_UNITS_PER_MATERIAL,
    VISUAL_UNDERSTANDING_ENABLED,
    YOUTUBE_TRANSCRIPT_LANGUAGES,
)
from .embeddings import (
    EmbeddingProvider,
    EmbeddingUnavailableError,
    get_embedding_provider,
)
from .extraction import extract_image, extract_pdf, extract_pptx
from .ocr import OCRReader, OCRUnavailableError, get_ocr_reader
from .resource_store import ProcessingJob, ResourceStore, ResourceStoreError
from .youtube_ingestion import (
    YouTubeCaptionReader,
    YouTubeTranscriptError,
    parse_youtube_url,
)
from .visual_understanding import (
    VisualAnalyzer,
    VisualUnderstandingError,
    build_visual_analyzer,
    enrich_with_visual_understanding,
)


SAFE_GENERIC_FAILURE = "The material could not be processed."


def process_next_job(
    store: ResourceStore,
    upload_dir: Path,
    *,
    ocr_factory: Callable[[], OCRReader] = get_ocr_reader,
    embedding_factory: Callable[[], EmbeddingProvider] = get_embedding_provider,
    caption_factory: Callable[[], YouTubeCaptionReader] = (
        lambda: YouTubeCaptionReader(YOUTUBE_TRANSCRIPT_LANGUAGES)
    ),
    visual_factory: Callable[[ResourceStore], VisualAnalyzer] = build_visual_analyzer,
) -> ProcessingJob | None:
    """Claim and complete at most one queued job in the calling process."""
    job = store.claim_next_extraction()
    if job is None:
        return None

    resource = store.get_by_resource_id(job.resource_id)
    if resource is None:
        store.fail_job(job.job_id, job.resource_id, "The uploaded material was not found.")
        return store.get_extraction_job(job.resource_id)

    def report_progress(current: int, total: int) -> None:
        store.update_job_progress(job.job_id, current, total)

    try:
        cached_content = store.cached_extraction(
            resource.resource_id, EXTRACTION_PIPELINE_VERSION
        )
        content = cached_content
        if content is None:
            if resource.extension == ".youtube":
                if not resource.source_url:
                    raise ValueError("The YouTube source link is missing.")
                video_id = parse_youtube_url(resource.source_url).video_id
                content = caption_factory().fetch(video_id)
                report_progress(len(content), len(content))
            else:
                path = upload_dir / resource.stored_filename
                if not path.is_file():
                    raise OSError("The uploaded material file is missing.")
                extractor = {
                    ".pdf": extract_pdf,
                    ".pptx": extract_pptx,
                    ".png": extract_image,
                    ".jpg": extract_image,
                    ".jpeg": extract_image,
                }.get(resource.extension)
                if extractor is None:
                    raise ValueError("This material type is not supported.")
                content = extractor(path, ocr_factory(), report_progress)
                if VISUAL_UNDERSTANDING_ENABLED:
                    content = enrich_with_visual_understanding(
                        path,
                        resource.extension,
                        content,
                        visual_factory(store),
                        VISUAL_MAX_UNITS_PER_MATERIAL,
                    )

        if not any(item["has_text"] for item in content):
            unit_name = {".pdf": "pages", ".pptx": "slides"}.get(
                resource.extension, "image"
            )
            raise ValueError(
                f"No readable text was found in this material's {unit_name} "
                "after text extraction and OCR."
            )
        chunks = build_chunks(
            resource.resource_id,
            resource.source_type,
            content,
            CHUNKING_PIPELINE_VERSION,
        )
        embedder = embedding_factory()
        vectors = embedder.embed_documents([chunk.text for chunk in chunks])
        if len(vectors) != len(chunks):
            raise EmbeddingUnavailableError(
                "The local embedding model returned an incomplete index."
            )
        embeddings = {
            chunk.chunk_id: vector for chunk, vector in zip(chunks, vectors)
        }
        if cached_content is not None:
            store.replace_chunks(
                resource.resource_id,
                chunks,
                CHUNKING_PIPELINE_VERSION,
                embedding_model=embedder.model_name,
                embeddings=embeddings,
            )
        else:
            store.save_processed_content(
                resource.resource_id,
                content,
                EXTRACTION_PIPELINE_VERSION,
                chunks,
                CHUNKING_PIPELINE_VERSION,
                embedding_model=embedder.model_name,
                embeddings=embeddings,
            )
        store.complete_job(job.job_id)
    except (
        OCRUnavailableError,
        YouTubeTranscriptError,
        VisualUnderstandingError,
    ) as error:
        store.fail_job(
            job.job_id,
            job.resource_id,
            str(error),
        )
    except EmbeddingUnavailableError as error:
        store.fail_job(job.job_id, job.resource_id, str(error))
    except (OSError, ValueError) as error:
        store.fail_job(job.job_id, job.resource_id, str(error))
    except ResourceStoreError:
        raise
    except Exception:
        store.fail_job(job.job_id, job.resource_id, SAFE_GENERIC_FAILURE)

    return store.get_extraction_job(job.resource_id)

