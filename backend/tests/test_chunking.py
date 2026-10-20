"""Deterministic chunking and provenance persistence tests."""

import pytest

from backend.chunking import build_chunks, split_text
from backend.config import PROCESSING_PIPELINE_VERSION
from backend.processing import process_next_job
from backend.resource_store import ResourceStore


RESOURCE_ID = "a" * 32
CHUNK_VERSION = "semantic-boundary-v1"


def extracted_page(number: int, text: str, method: str = "native"):
    return {
        "reference_type": "page",
        "reference_number": number,
        "text": text,
        "native_text": text,
        "ocr_text": "",
        "has_text": bool(text),
        "ocr_applied": True,
        "extraction_method": method,
    }


def test_chunks_are_bounded_deterministic_and_never_cross_pages():
    first_page = "Overview\n\n" + ("Gradient descent updates model weights. " * 80)
    content = [
        extracted_page(1, first_page, "native+ocr"),
        extracted_page(2, "SECOND_PAGE_MARKER A separate concept."),
    ]

    chunks = build_chunks(RESOURCE_ID, "pdf", content, CHUNK_VERSION)
    repeated = build_chunks(RESOURCE_ID, "pdf", content, CHUNK_VERSION)

    assert chunks == repeated
    assert len(chunks) > 2
    assert all(0 < len(chunk.text) <= 1_200 for chunk in chunks)
    assert all(chunk.reference_type == "page" for chunk in chunks)
    assert all(
        "SECOND_PAGE_MARKER" not in chunk.text
        for chunk in chunks
        if chunk.reference_number == 1
    )
    assert [chunk.chunk_index for chunk in chunks if chunk.reference_number == 2] == [1]
    assert chunks[0].extraction_method == "native+ocr"


def test_split_text_validates_limits_and_skips_blank_content():
    assert split_text(" \n\n ") == []
    with pytest.raises(ValueError, match="at least 100"):
        split_text("content", max_characters=50)
    with pytest.raises(ValueError, match="smaller"):
        split_text("content", max_characters=100, overlap_characters=100)


def test_chunking_rejects_mismatched_provenance():
    with pytest.raises(ValueError, match="citation provenance"):
        build_chunks(
            RESOURCE_ID,
            "pdf",
            [{"reference_type": "slide", "reference_number": 1, "text": "Wrong"}],
            CHUNK_VERSION,
        )


def test_processed_content_and_chunks_persist_atomically(tmp_path):
    database = tmp_path / "learnflow.db"
    store = ResourceStore(database)
    resource, _ = store.create(
        resource_id=RESOURCE_ID,
        original_filename="lesson.pdf",
        stored_filename=f"{RESOURCE_ID}.pdf",
        source_type="pdf",
        extension=".pdf",
        content_hash="b" * 64,
        size_bytes=128,
    )
    content = [extracted_page(3, "A persisted lesson section with exact provenance.")]
    chunks = build_chunks(resource.resource_id, "pdf", content, CHUNK_VERSION)

    store.save_processed_content(
        resource.resource_id,
        content,
        "native-rapidocr-v1",
        chunks,
        CHUNK_VERSION,
    )

    reopened = ResourceStore(database)
    persisted = reopened.list_chunks(resource.resource_id, CHUNK_VERSION)
    assert persisted == chunks
    assert persisted[0].reference_number == 3
    assert reopened.get_by_resource_id(resource.resource_id).status == "ready"

    reopened.delete(resource.resource_id)
    assert reopened.list_chunks(resource.resource_id) == []


def test_cached_extraction_is_backfilled_without_repeating_ocr(tmp_path):
    store = ResourceStore(tmp_path / "learnflow.db")
    resource, _ = store.create(
        resource_id=RESOURCE_ID,
        original_filename="cached.pdf",
        stored_filename=f"{RESOURCE_ID}.pdf",
        source_type="pdf",
        extension=".pdf",
        content_hash="c" * 64,
        size_bytes=128,
    )
    content = [extracted_page(1, "Already extracted text should only be chunked.")]
    store.save_extraction(resource.resource_id, content, "native-rapidocr-v1")
    store.enqueue_extraction(resource.resource_id, PROCESSING_PIPELINE_VERSION)

    def unexpected_ocr():
        raise AssertionError("Cached extraction must not reload OCR")

    result = process_next_job(store, tmp_path, ocr_factory=unexpected_ocr)

    assert result is not None
    assert result.status == "completed"
    assert store.list_chunks(resource.resource_id, CHUNK_VERSION)[0].reference_number == 1

