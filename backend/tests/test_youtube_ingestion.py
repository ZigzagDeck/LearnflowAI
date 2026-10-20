"""YouTube URL validation, caption normalization, and timestamp persistence."""

import asyncio
from types import SimpleNamespace

import pytest

from backend.config import CHUNKING_PIPELINE_VERSION, PROCESSING_PIPELINE_VERSION
from backend.processing import process_next_job
from backend.resource_store import ResourceStore
from backend.retrieval import SQLiteHybridRetriever
from backend.tests.fake_embeddings import TinyEmbeddingProvider
from backend.youtube_ingestion import YouTubeCaptionReader, parse_youtube_url


class FakeTranscriptClient:
    def fetch(self, video_id, languages):
        assert video_id == "dQw4w9WgXcQ"
        assert languages == ("en", "hi")
        return [
            SimpleNamespace(text="Neural networks learn patterns.", start=1.5, duration=2.5),
            SimpleNamespace(text="Backpropagation updates weights.", start=4.0, duration=3.0),
        ]


def test_youtube_url_parser_accepts_known_video_shapes_only():
    expected = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert parse_youtube_url(expected).canonical_url == expected
    assert parse_youtube_url("https://youtu.be/dQw4w9WgXcQ").canonical_url == expected
    assert parse_youtube_url("https://youtube.com/shorts/dQw4w9WgXcQ").canonical_url == expected

    with pytest.raises(ValueError, match="Only HTTPS YouTube"):
        parse_youtube_url("https://example.com/watch?v=dQw4w9WgXcQ")
    with pytest.raises(ValueError, match="direct link"):
        parse_youtube_url("https://youtube.com/playlist?list=dQw4w9WgXcQ")


def test_caption_reader_preserves_real_timestamps():
    content = YouTubeCaptionReader(
        ("en", "hi"), client=FakeTranscriptClient()
    ).fetch("dQw4w9WgXcQ")

    assert content[0]["start_seconds"] == 1.5
    assert content[0]["end_seconds"] == 4.0
    assert content[1]["text"] == "Backpropagation updates weights."


def test_youtube_processing_indexes_timestamped_video_without_ocr(tmp_path):
    store = ResourceStore(tmp_path / "learnflow.db")
    resource, _ = store.create(
        resource_id="a" * 32,
        original_filename="YouTube video dQw4w9WgXcQ",
        stored_filename="youtube-dQw4w9WgXcQ",
        source_type="video",
        extension=".youtube",
        content_hash="b" * 64,
        size_bytes=43,
        source_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    )
    store.enqueue_extraction(resource.resource_id, PROCESSING_PIPELINE_VERSION)
    caption_reader = YouTubeCaptionReader(("en", "hi"), client=FakeTranscriptClient())

    job = process_next_job(
        store,
        tmp_path,
        ocr_factory=lambda: (_ for _ in ()).throw(AssertionError("OCR must not run")),
        embedding_factory=TinyEmbeddingProvider,
        caption_factory=lambda: caption_reader,
    )

    assert job is not None and job.status == "completed"
    chunks = store.list_chunks(resource.resource_id, CHUNKING_PIPELINE_VERSION)
    assert len(chunks) == 1
    assert chunks[0].start_seconds == 1.5
    assert chunks[0].end_seconds == 7.0

    retriever = SQLiteHybridRetriever(store, TinyEmbeddingProvider())
    before = asyncio.run(
        retriever.retrieve_video("backpropagation", resource.resource_id, 5.0)
    )
    after = asyncio.run(
        retriever.retrieve_video("backpropagation", resource.resource_id, 7.0)
    )
    assert before == []
    assert after[0].citation.start_seconds == 1.5
    assert after[0].citation.end_seconds == 7.0
