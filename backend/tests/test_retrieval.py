"""Local FTS5 retrieval and citation adapter tests."""

import asyncio

from backend.chunking import build_chunks
from backend.config import CHUNKING_PIPELINE_VERSION, EXTRACTION_PIPELINE_VERSION
from backend.resource_store import ResourceStore
from backend.retrieval import SQLiteHybridRetriever, SQLiteLexicalRetriever
from backend.tests.fake_embeddings import TinyEmbeddingProvider


def add_pdf(
    store: ResourceStore,
    resource_id: str,
    content_hash: str,
    text: str,
    *,
    with_embeddings: bool = False,
):
    resource, _ = store.create(
        resource_id=resource_id,
        original_filename=f"{resource_id}.pdf",
        stored_filename=f"{resource_id}.pdf",
        source_type="pdf",
        extension=".pdf",
        content_hash=content_hash,
        size_bytes=128,
    )
    content = [
        {
            "reference_type": "page",
            "reference_number": 2,
            "text": text,
            "native_text": text,
            "ocr_text": "",
            "has_text": True,
            "ocr_applied": True,
            "extraction_method": "native",
        }
    ]
    chunks = build_chunks(
        resource.resource_id,
        resource.source_type,
        content,
        CHUNKING_PIPELINE_VERSION,
    )
    embedder = TinyEmbeddingProvider()
    vectors = embedder.embed_documents([chunk.text for chunk in chunks])
    embedding_options = (
        {
            "embedding_model": embedder.model_name,
            "embeddings": {
                chunk.chunk_id: vector for chunk, vector in zip(chunks, vectors)
            },
        }
        if with_embeddings
        else {}
    )
    store.save_processed_content(
        resource.resource_id,
        content,
        EXTRACTION_PIPELINE_VERSION,
        chunks,
        CHUNKING_PIPELINE_VERSION,
        **embedding_options,
    )
    return resource, chunks


def test_fts_search_is_filtered_to_allowed_resources(tmp_path):
    store = ResourceStore(tmp_path / "learnflow.db")
    allowed, _ = add_pdf(
        store,
        "a" * 32,
        "1" * 64,
        "Gradient descent updates neural network weights during training.",
    )
    private, _ = add_pdf(
        store,
        "b" * 32,
        "2" * 64,
        "Private gradient descent notes must not cross the source boundary.",
    )

    results = store.search_chunks(
        "gradient descent",
        [allowed.resource_id],
        CHUNKING_PIPELINE_VERSION,
    )

    assert results
    assert {result.chunk.resource_id for result in results} == {allowed.resource_id}
    assert all(result.score >= 0 for result in results)
    assert private.resource_id not in {result.chunk.resource_id for result in results}


def test_fts_query_is_safely_tokenized_and_empty_scope_returns_nothing(tmp_path):
    store = ResourceStore(tmp_path / "learnflow.db")
    resource, _ = add_pdf(
        store,
        "c" * 32,
        "3" * 64,
        "Photosynthesis converts light energy into chemical energy.",
    )

    results = store.search_chunks(
        'photosynthesis OR "unterminated:*',
        [resource.resource_id],
        CHUNKING_PIPELINE_VERSION,
    )

    assert results[0].chunk.resource_id == resource.resource_id
    assert store.search_chunks("photosynthesis", [], CHUNKING_PIPELINE_VERSION) == []
    assert store.search_chunks("!!!", [resource.resource_id], CHUNKING_PIPELINE_VERSION) == []


def test_lexical_retriever_returns_contract_valid_page_citation(tmp_path):
    store = ResourceStore(tmp_path / "learnflow.db")
    resource, chunks = add_pdf(
        store,
        "d" * 32,
        "4" * 64,
        "Backpropagation calculates gradients for each network layer.",
    )
    retriever = SQLiteLexicalRetriever(store, limit=4)

    hits = asyncio.run(
        retriever.retrieve_documents("backpropagation gradients", [resource.resource_id])
    )

    assert len(hits) == 1
    assert hits[0].citation.source_id == resource.resource_id
    assert hits[0].citation.chunk_id == chunks[0].chunk_id
    assert hits[0].citation.page == 2
    assert hits[0].text == chunks[0].text


def test_deleting_resource_removes_fts_entries(tmp_path):
    store = ResourceStore(tmp_path / "learnflow.db")
    resource, _ = add_pdf(
        store,
        "e" * 32,
        "5" * 64,
        "A uniquely searchable deletion marker.",
    )
    store.delete(resource.resource_id)

    assert store.search_chunks(
        "deletion marker",
        [resource.resource_id],
        CHUNKING_PIPELINE_VERSION,
    ) == []


def test_dense_search_is_persistent_and_filtered_to_allowed_resources(tmp_path):
    database = tmp_path / "learnflow.db"
    store = ResourceStore(database)
    allowed, allowed_chunks = add_pdf(
        store,
        "f" * 32,
        "6" * 64,
        "Gradient descent adjusts model parameters during learning.",
        with_embeddings=True,
    )
    private, _ = add_pdf(
        store,
        "1" * 32,
        "7" * 64,
        "Private optimization notes must remain isolated.",
        with_embeddings=True,
    )
    embedder = TinyEmbeddingProvider()

    results = ResourceStore(database).search_embeddings(
        embedder.embed_query("optimization"),
        [allowed.resource_id],
        CHUNKING_PIPELINE_VERSION,
        embedder.model_name,
    )

    assert [result.chunk.chunk_id for result in results] == [
        allowed_chunks[0].chunk_id
    ]
    assert private.resource_id not in {result.chunk.resource_id for result in results}


def test_hybrid_retriever_recovers_semantic_match_without_lexical_overlap(tmp_path):
    store = ResourceStore(tmp_path / "learnflow.db")
    resource, chunks = add_pdf(
        store,
        "2" * 32,
        "8" * 64,
        "Gradient descent adjusts model parameters during learning.",
        with_embeddings=True,
    )
    assert store.search_chunks(
        "optimization", [resource.resource_id], CHUNKING_PIPELINE_VERSION
    ) == []
    retriever = SQLiteHybridRetriever(store, TinyEmbeddingProvider(), limit=4)

    hits = asyncio.run(
        retriever.retrieve_documents("optimization", [resource.resource_id])
    )

    assert len(hits) == 1
    assert hits[0].citation.chunk_id == chunks[0].chunk_id
    assert hits[0].citation.page == 2
    assert hits[0].score > 0

