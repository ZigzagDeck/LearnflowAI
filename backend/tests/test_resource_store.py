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
