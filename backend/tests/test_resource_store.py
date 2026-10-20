"""SQLite registry persistence, status, and extraction-cache tests."""
from backend.resource_store import ResourceStore


def create_record(store: ResourceStore):
    return store.create(
        resource_id="a" * 32,
        original_filename="lesson.pdf",
        stored_filename=f"{'a' * 32}.pdf",
        source_type="pdf",
        extension=".pdf",
        content_hash="b" * 64,
        size_bytes=128,
    )


def test_registry_persists_records_and_cached_extraction(tmp_path):
    database = tmp_path / "data" / "learnflow.db"
    store = ResourceStore(database)
    record, created = create_record(store)
    assert created is True
    assert record.status == "uploaded"

    content = [{"reference_type": "page", "reference_number": 1, "text": "Lesson"}]
    store.set_status(record.resource_id, "processing")
    store.save_extraction(record.resource_id, content, "pipeline-v1")

    reopened = ResourceStore(database)
    persisted = reopened.get_by_resource_id(record.resource_id)
    assert persisted is not None
    assert persisted.status == "ready"
    assert persisted.has_cached_extraction is True
    assert reopened.cached_extraction(record.resource_id, "pipeline-v1") == content
    assert reopened.cached_extraction(record.resource_id, "pipeline-v2") is None


def test_duplicate_hash_returns_existing_record(tmp_path):
    store = ResourceStore(tmp_path / "learnflow.db")
    first, first_created = create_record(store)
    second, second_created = store.create(
        resource_id="c" * 32,
        original_filename="copy.pdf",
        stored_filename=f"{'c' * 32}.pdf",
        source_type="pdf",
        extension=".pdf",
        content_hash="b" * 64,
        size_bytes=128,
    )

    assert first_created is True
    assert second_created is False
    assert second.resource_id == first.resource_id
    assert len(store.list()) == 1


def test_failed_status_clears_when_extraction_is_saved(tmp_path):
    store = ResourceStore(tmp_path / "learnflow.db")
    record, _ = create_record(store)
    store.set_status(record.resource_id, "failed", "Safe failure")
    failed = store.get_by_resource_id(record.resource_id)
    assert failed is not None
    assert failed.error == "Safe failure"

    store.save_extraction(
        record.resource_id, [{"text": "Recovered"}], "pipeline-v1"
    )
    ready = store.get_by_resource_id(record.resource_id)
    assert ready is not None
    assert ready.status == "ready"
    assert ready.error is None


def test_processing_job_is_durable_and_reports_progress(tmp_path):
    database = tmp_path / "learnflow.db"
    store = ResourceStore(database)
    record, _ = create_record(store)

    queued = store.enqueue_extraction(record.resource_id, "pipeline-v1")
    assert queued.status == "queued"
    claimed = store.claim_next_extraction()
    assert claimed is not None
    assert claimed.status == "processing"
    assert claimed.attempts == 1

    store.update_job_progress(claimed.job_id, 2, 4)
    persisted = ResourceStore(database).get_extraction_job(record.resource_id)
    assert persisted is not None
    assert persisted.public_dict()["progress_percent"] == 50

    store.save_extraction(record.resource_id, [{"text": "Ready"}], "pipeline-v1")
    store.complete_job(claimed.job_id)
    completed = store.get_extraction_job(record.resource_id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.public_dict()["progress_percent"] == 100


def test_failed_job_requires_explicit_retry(tmp_path):
    store = ResourceStore(tmp_path / "learnflow.db")
    record, _ = create_record(store)
    store.enqueue_extraction(record.resource_id, "pipeline-v1")
    claimed = store.claim_next_extraction()
    assert claimed is not None
    store.fail_job(claimed.job_id, record.resource_id, "Readable failure")

    unchanged = store.enqueue_extraction(record.resource_id, "pipeline-v1")
    assert unchanged.status == "failed"
    retried = store.enqueue_extraction(
        record.resource_id, "pipeline-v1", retry_failed=True
    )
    assert retried.status == "queued"
    assert retried.attempts == 0


def test_stale_processing_job_is_requeued_after_interruption(tmp_path):
    store = ResourceStore(tmp_path / "learnflow.db")
    record, _ = create_record(store)
    store.enqueue_extraction(record.resource_id, "pipeline-v1")
    assert store.claim_next_extraction() is not None

    assert store.recover_interrupted_jobs(0) == 1
    recovered = store.get_extraction_job(record.resource_id)
    assert recovered is not None
    assert recovered.status == "queued"
    assert store.get_by_resource_id(record.resource_id).status == "uploaded"


def test_store_allows_only_one_heavy_job_at_a_time(tmp_path):
    store = ResourceStore(tmp_path / "learnflow.db")
    first, _ = create_record(store)
    second, _ = store.create(
        resource_id="c" * 32,
        original_filename="second.pdf",
        stored_filename=f"{'c' * 32}.pdf",
        source_type="pdf",
        extension=".pdf",
        content_hash="d" * 64,
        size_bytes=256,
    )
    store.enqueue_extraction(first.resource_id, "pipeline-v1")
    store.enqueue_extraction(second.resource_id, "pipeline-v1")

    claimed = store.claim_next_extraction()
    assert claimed is not None
    assert store.claim_next_extraction() is None
