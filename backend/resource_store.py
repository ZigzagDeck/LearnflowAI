"""SQLite-backed material metadata, extraction cache, and local indexes."""
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
import math
import json
from pathlib import Path
import re
import sqlite3
import struct
import uuid

from .chunking import NormalizedChunk


VALID_STATUSES = {"uploaded", "processing", "ready", "failed"}


class ResourceStoreError(RuntimeError):
    """A safe boundary for local metadata persistence failures."""


class MonthlyUsageLimitError(ResourceStoreError):
    """A locally enforced monthly external-service limit was reached."""


@dataclass(frozen=True)
class ResourceRecord:
    resource_id: str
    original_filename: str
    stored_filename: str
    source_type: str
    extension: str
    content_hash: str
    size_bytes: int
    status: str
    error: str | None
    has_cached_extraction: bool
    extraction_version: str | None
    created_at: str
    updated_at: str

    def public_dict(self) -> dict[str, object]:
        payload = asdict(self)
        # Content hashes are internal cache keys, not public resource metadata.
        payload.pop("content_hash")
        return payload


@dataclass(frozen=True)
class ProcessingJob:
    job_id: str
    resource_id: str
    pipeline_version: str
    status: str
    attempts: int
    progress_current: int
    progress_total: int | None
    error: str | None
    created_at: str
    updated_at: str
    started_at: str | None
    completed_at: str | None

    def public_dict(self) -> dict[str, object]:
        payload = asdict(self)
        if self.progress_total:
            payload["progress_percent"] = min(
                100, round(self.progress_current * 100 / self.progress_total)
            )
        else:
            payload["progress_percent"] = 0
        return payload


@dataclass(frozen=True)
class ChunkSearchHit:
    chunk: NormalizedChunk
    score: float


class ResourceStore:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            self._initialize()
        except (OSError, sqlite3.Error) as exc:
            raise ResourceStoreError("Resource metadata storage is unavailable.") from exc

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS resources (
                    resource_id TEXT PRIMARY KEY,
                    original_filename TEXT NOT NULL,
                    stored_filename TEXT NOT NULL UNIQUE,
                    source_type TEXT NOT NULL,
                    extension TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE,
                    size_bytes INTEGER NOT NULL CHECK (size_bytes > 0),
                    status TEXT NOT NULL CHECK (
                        status IN ('uploaded', 'processing', 'ready', 'failed')
                    ),
                    error TEXT,
                    extraction_json TEXT,
                    extraction_version TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(resources)").fetchall()
            }
            if "extraction_version" not in columns:
                connection.execute(
                    "ALTER TABLE resources ADD COLUMN extraction_version TEXT"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_resources_updated_at "
                "ON resources(updated_at DESC)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS processing_jobs (
                    job_id TEXT PRIMARY KEY,
                    resource_id TEXT NOT NULL UNIQUE,
                    pipeline_version TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (
                        status IN ('queued', 'processing', 'completed', 'failed')
                    ),
                    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
                    progress_current INTEGER NOT NULL DEFAULT 0
                        CHECK (progress_current >= 0),
                    progress_total INTEGER CHECK (progress_total > 0),
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    FOREIGN KEY(resource_id) REFERENCES resources(resource_id)
                        ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_processing_jobs_status_created "
                "ON processing_jobs(status, created_at)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS monthly_service_usage (
                    provider TEXT NOT NULL,
                    period TEXT NOT NULL,
                    units INTEGER NOT NULL CHECK (units >= 0),
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(provider, period)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    resource_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    reference_type TEXT NOT NULL,
                    reference_number INTEGER NOT NULL CHECK (reference_number > 0),
                    chunk_index INTEGER NOT NULL CHECK (chunk_index > 0),
                    text TEXT NOT NULL CHECK (length(text) > 0),
                    extraction_method TEXT NOT NULL,
                    chunk_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(resource_id) REFERENCES resources(resource_id)
                        ON DELETE CASCADE,
                    UNIQUE(
                        resource_id, chunk_version, reference_type,
                        reference_number, chunk_index
                    )
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_chunks_resource_reference "
                "ON chunks(resource_id, reference_type, reference_number, chunk_index)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS chunk_embeddings (
                    chunk_id TEXT PRIMARY KEY,
                    model_name TEXT NOT NULL,
                    dimensions INTEGER NOT NULL CHECK (dimensions > 0),
                    vector BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id)
                        ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_model "
                "ON chunk_embeddings(model_name)"
            )
            connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    chunk_id UNINDEXED,
                    resource_id UNINDEXED,
                    text,
                    tokenize = 'unicode61 remove_diacritics 2'
                )
                """
            )
            connection.execute(
                """
                INSERT INTO chunks_fts (chunk_id, resource_id, text)
                SELECT chunk_id, resource_id, text FROM chunks
                WHERE NOT EXISTS (
                    SELECT 1 FROM chunks_fts
                    WHERE chunks_fts.chunk_id = chunks.chunk_id
                )
                """
            )

    @staticmethod
    def _record(row: sqlite3.Row | None) -> ResourceRecord | None:
        if row is None:
            return None
        return ResourceRecord(
            resource_id=row["resource_id"],
            original_filename=row["original_filename"],
            stored_filename=row["stored_filename"],
            source_type=row["source_type"],
            extension=row["extension"],
            content_hash=row["content_hash"],
            size_bytes=row["size_bytes"],
            status=row["status"],
            error=row["error"],
            has_cached_extraction=row["extraction_json"] is not None,
            extraction_version=row["extraction_version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _job(row: sqlite3.Row | None) -> ProcessingJob | None:
        if row is None:
            return None
        return ProcessingJob(
            job_id=row["job_id"],
            resource_id=row["resource_id"],
            pipeline_version=row["pipeline_version"],
            status=row["status"],
            attempts=row["attempts"],
            progress_current=row["progress_current"],
            progress_total=row["progress_total"],
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
        )

    @staticmethod
    def _chunk(row: sqlite3.Row) -> NormalizedChunk:
        return NormalizedChunk(
            chunk_id=row["chunk_id"],
            resource_id=row["resource_id"],
            source_type=row["source_type"],
            reference_type=row["reference_type"],
            reference_number=row["reference_number"],
            chunk_index=row["chunk_index"],
            text=row["text"],
            extraction_method=row["extraction_method"],
            chunk_version=row["chunk_version"],
        )

    def find_by_hash(self, content_hash: str) -> ResourceRecord | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM resources WHERE content_hash = ?", (content_hash,)
                ).fetchone()
            return self._record(row)
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not read resource metadata.") from exc

    def get_by_resource_id(self, resource_id: str) -> ResourceRecord | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM resources WHERE resource_id = ?", (resource_id,)
                ).fetchone()
            return self._record(row)
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not read resource metadata.") from exc

    def get_by_stored_filename(self, stored_filename: str) -> ResourceRecord | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM resources WHERE stored_filename = ?",
                    (stored_filename,),
                ).fetchone()
            return self._record(row)
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not read resource metadata.") from exc

    def create(
        self,
        *,
        resource_id: str,
        original_filename: str,
        stored_filename: str,
        source_type: str,
        extension: str,
        content_hash: str,
        size_bytes: int,
    ) -> tuple[ResourceRecord, bool]:
        now = datetime.now(UTC).isoformat()
        try:
            with self._connect() as connection:
                try:
                    connection.execute(
                        """
                        INSERT INTO resources (
                            resource_id, original_filename, stored_filename,
                            source_type, extension, content_hash, size_bytes,
                            status, error, extraction_json, extraction_version,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'uploaded', NULL, NULL, NULL, ?, ?)
                        """,
                        (
                            resource_id,
                            original_filename,
                            stored_filename,
                            source_type,
                            extension,
                            content_hash,
                            size_bytes,
                            now,
                            now,
                        ),
                    )
                    created = True
                except sqlite3.IntegrityError:
                    created = False
                row = connection.execute(
                    "SELECT * FROM resources WHERE content_hash = ?", (content_hash,)
                ).fetchone()
            record = self._record(row)
            if record is None:
                raise ResourceStoreError("Could not create resource metadata.")
            return record, created
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not create resource metadata.") from exc

    def delete(self, resource_id: str) -> None:
        try:
            with self._connect() as connection:
                connection.execute(
                    "DELETE FROM chunks_fts WHERE resource_id = ?", (resource_id,)
                )
                connection.execute(
                    "DELETE FROM resources WHERE resource_id = ?", (resource_id,)
                )
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not remove stale resource metadata.") from exc

    def list(self) -> list[ResourceRecord]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT * FROM resources ORDER BY updated_at DESC"
                ).fetchall()
            return [record for row in rows if (record := self._record(row))]
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not list resource metadata.") from exc

    def reserve_monthly_usage(
        self, provider: str, units: int, monthly_limit: int
    ) -> int:
        """Atomically reserve billable units before an external request."""
        if not provider or units < 1 or monthly_limit < 1:
            raise ValueError("Usage reservation values must be positive.")
        period = datetime.now(UTC).strftime("%Y-%m")
        now = datetime.now(UTC).isoformat()
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """
                    SELECT units FROM monthly_service_usage
                    WHERE provider = ? AND period = ?
                    """,
                    (provider, period),
                ).fetchone()
                current = int(row["units"]) if row else 0
                updated = current + units
                if updated > monthly_limit:
                    raise MonthlyUsageLimitError(
                        f"The configured monthly usage limit for {provider} "
                        "has been reached."
                    )
                connection.execute(
                    """
                    INSERT INTO monthly_service_usage (
                        provider, period, units, updated_at
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(provider, period) DO UPDATE SET
                        units = excluded.units,
                        updated_at = excluded.updated_at
                    """,
                    (provider, period, updated, now),
                )
            return updated
        except MonthlyUsageLimitError:
            raise
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not reserve external service usage.") from exc

    def current_monthly_usage(self, provider: str) -> tuple[str, int]:
        period = datetime.now(UTC).strftime("%Y-%m")
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT units FROM monthly_service_usage
                    WHERE provider = ? AND period = ?
                    """,
                    (provider, period),
                ).fetchone()
            return period, int(row["units"]) if row else 0
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not read external service usage.") from exc

    def set_status(
        self, resource_id: str, status: str, error: str | None = None
    ) -> None:
        if status not in VALID_STATUSES:
            raise ValueError(f"Unsupported resource status: {status}")
        now = datetime.now(UTC).isoformat()
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE resources
                    SET status = ?, error = ?, updated_at = ?
                    WHERE resource_id = ?
                    """,
                    (status, error, now, resource_id),
                )
            if cursor.rowcount != 1:
                raise ResourceStoreError("Resource metadata was not found.")
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not update resource metadata.") from exc

    def save_extraction(
        self,
        resource_id: str,
        content: list[dict[str, object]],
        extraction_version: str,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        serialized = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE resources
                    SET extraction_json = ?, extraction_version = ?,
                        status = 'ready', error = NULL, updated_at = ?
                    WHERE resource_id = ?
                    """,
                    (serialized, extraction_version, now, resource_id),
                )
            if cursor.rowcount != 1:
                raise ResourceStoreError("Resource metadata was not found.")
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not cache extracted content.") from exc

    @staticmethod
    def _validate_chunks(
        resource_id: str,
        chunks: list[NormalizedChunk],
        chunk_version: str,
    ) -> None:
        if not chunks:
            raise ValueError("Processed content did not produce any searchable chunks.")
        if any(
            chunk.resource_id != resource_id
            or chunk.chunk_version != chunk_version
            for chunk in chunks
        ):
            raise ValueError("Chunk metadata does not match the processed resource.")

    @staticmethod
    def _insert_chunks(
        connection: sqlite3.Connection,
        chunks: list[NormalizedChunk],
        created_at: str,
    ) -> None:
        connection.executemany(
            """
            INSERT INTO chunks (
                chunk_id, resource_id, source_type, reference_type,
                reference_number, chunk_index, text, extraction_method,
                chunk_version, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    chunk.chunk_id,
                    chunk.resource_id,
                    chunk.source_type,
                    chunk.reference_type,
                    chunk.reference_number,
                    chunk.chunk_index,
                    chunk.text,
                    chunk.extraction_method,
                    chunk.chunk_version,
                    created_at,
                )
                for chunk in chunks
            ],
        )
        connection.executemany(
            """
            INSERT INTO chunks_fts (chunk_id, resource_id, text)
            VALUES (?, ?, ?)
            """,
            [
                (chunk.chunk_id, chunk.resource_id, chunk.text)
                for chunk in chunks
            ],
        )

    @staticmethod
    def _validate_embeddings(
        chunks: list[NormalizedChunk],
        embedding_model: str | None,
        embeddings: Mapping[str, Sequence[float]] | None,
    ) -> int | None:
        if embedding_model is None and embeddings is None:
            return None
        if not embedding_model or embeddings is None:
            raise ValueError("Embedding model and vectors must be provided together.")
        expected_ids = {chunk.chunk_id for chunk in chunks}
        if set(embeddings) != expected_ids:
            raise ValueError("Every normalized chunk must have exactly one embedding.")
        dimensions = {len(vector) for vector in embeddings.values()}
        if len(dimensions) != 1 or next(iter(dimensions), 0) < 1:
            raise ValueError("Chunk embeddings must have one non-zero dimension.")
        if any(
            not all(math.isfinite(float(value)) for value in vector)
            for vector in embeddings.values()
        ):
            raise ValueError("Chunk embeddings must contain only finite values.")
        return next(iter(dimensions))

    @staticmethod
    def _insert_embeddings(
        connection: sqlite3.Connection,
        embedding_model: str,
        embeddings: Mapping[str, Sequence[float]],
        dimensions: int,
        created_at: str,
    ) -> None:
        connection.executemany(
            """
            INSERT INTO chunk_embeddings (
                chunk_id, model_name, dimensions, vector, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    chunk_id,
                    embedding_model,
                    dimensions,
                    struct.pack(f"<{dimensions}f", *vector),
                    created_at,
                )
                for chunk_id, vector in embeddings.items()
            ],
        )

    def save_processed_content(
        self,
        resource_id: str,
        content: list[dict[str, object]],
        extraction_version: str,
        chunks: list[NormalizedChunk],
        chunk_version: str,
        *,
        embedding_model: str | None = None,
        embeddings: Mapping[str, Sequence[float]] | None = None,
    ) -> None:
        """Atomically persist extraction, chunks, optional vectors, and ready status."""
        self._validate_chunks(resource_id, chunks, chunk_version)
        dimensions = self._validate_embeddings(chunks, embedding_model, embeddings)
        now = datetime.now(UTC).isoformat()
        serialized = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "DELETE FROM chunks_fts WHERE resource_id = ?", (resource_id,)
                )
                connection.execute(
                    "DELETE FROM chunks WHERE resource_id = ?", (resource_id,)
                )
                self._insert_chunks(connection, chunks, now)
                if dimensions is not None and embedding_model and embeddings:
                    self._insert_embeddings(
                        connection,
                        embedding_model,
                        embeddings,
                        dimensions,
                        now,
                    )
                cursor = connection.execute(
                    """
                    UPDATE resources
                    SET extraction_json = ?, extraction_version = ?,
                        status = 'ready', error = NULL, updated_at = ?
                    WHERE resource_id = ?
                    """,
                    (serialized, extraction_version, now, resource_id),
                )
                if cursor.rowcount != 1:
                    raise ResourceStoreError("Resource metadata was not found.")
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not persist processed content.") from exc

    def replace_chunks(
        self,
        resource_id: str,
        chunks: list[NormalizedChunk],
        chunk_version: str,
        *,
        embedding_model: str | None = None,
        embeddings: Mapping[str, Sequence[float]] | None = None,
    ) -> None:
        """Backfill or rebuild chunks and vectors without repeating cached OCR."""
        self._validate_chunks(resource_id, chunks, chunk_version)
        dimensions = self._validate_embeddings(chunks, embedding_model, embeddings)
        now = datetime.now(UTC).isoformat()
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                exists = connection.execute(
                    "SELECT 1 FROM resources WHERE resource_id = ?", (resource_id,)
                ).fetchone()
                if exists is None:
                    raise ResourceStoreError("Resource metadata was not found.")
                connection.execute(
                    "DELETE FROM chunks_fts WHERE resource_id = ?", (resource_id,)
                )
                connection.execute(
                    "DELETE FROM chunks WHERE resource_id = ?", (resource_id,)
                )
                self._insert_chunks(connection, chunks, now)
                if dimensions is not None and embedding_model and embeddings:
                    self._insert_embeddings(
                        connection,
                        embedding_model,
                        embeddings,
                        dimensions,
                        now,
                    )
                connection.execute(
                    """
                    UPDATE resources
                    SET status = 'ready', error = NULL, updated_at = ?
                    WHERE resource_id = ?
                    """,
                    (now, resource_id),
                )
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not persist normalized chunks.") from exc

    def list_chunks(
        self, resource_id: str, chunk_version: str | None = None
    ) -> list[NormalizedChunk]:
        try:
            with self._connect() as connection:
                if chunk_version is None:
                    rows = connection.execute(
                        """
                        SELECT * FROM chunks WHERE resource_id = ?
                        ORDER BY reference_number, chunk_index
                        """,
                        (resource_id,),
                    ).fetchall()
                else:
                    rows = connection.execute(
                        """
                        SELECT * FROM chunks
                        WHERE resource_id = ? AND chunk_version = ?
                        ORDER BY reference_number, chunk_index
                        """,
                        (resource_id, chunk_version),
                    ).fetchall()
            return [self._chunk(row) for row in rows]
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not read normalized chunks.") from exc

    def search_chunks(
        self,
        query: str,
        allowed_resource_ids: list[str],
        chunk_version: str,
        *,
        limit: int = 8,
    ) -> list[ChunkSearchHit]:
        """Run local BM25 search, always constrained to an explicit source allow-list."""
        allowed_ids = list(dict.fromkeys(allowed_resource_ids))[:30]
        if not allowed_ids or limit < 1 or limit > 50:
            return []
        terms = [
            term[:64]
            for term in dict.fromkeys(re.findall(r"[^\W_]+", query.casefold()))
        ][:24]
        if not terms:
            return []
        match_expression = " OR ".join(f'"{term}"' for term in terms)
        placeholders = ",".join("?" for _ in allowed_ids)
        parameters: list[object] = [
            match_expression,
            chunk_version,
            *allowed_ids,
            limit,
        ]
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    f"""
                    SELECT chunks.*, bm25(chunks_fts) AS lexical_rank
                    FROM chunks_fts
                    JOIN chunks ON chunks.chunk_id = chunks_fts.chunk_id
                    WHERE chunks_fts MATCH ?
                        AND chunks.chunk_version = ?
                        AND chunks.resource_id IN ({placeholders})
                    ORDER BY lexical_rank ASC, chunks.chunk_id ASC
                    LIMIT ?
                    """,
                    parameters,
                ).fetchall()
            return [
                ChunkSearchHit(
                    chunk=self._chunk(row),
                    score=max(0.0, -float(row["lexical_rank"])),
                )
                for row in rows
            ]
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not search normalized chunks.") from exc

    def search_embeddings(
        self,
        query_vector: Sequence[float],
        allowed_resource_ids: list[str],
        chunk_version: str,
        embedding_model: str,
        *,
        limit: int = 8,
    ) -> list[ChunkSearchHit]:
        """Run bounded exact cosine search within an explicit source allow-list."""
        allowed_ids = list(dict.fromkeys(allowed_resource_ids))[:30]
        vector = [float(value) for value in query_vector]
        if not allowed_ids or limit < 1 or limit > 50 or not vector:
            return []
        if not all(math.isfinite(value) for value in vector):
            raise ValueError("Query embeddings must contain only finite values.")
        placeholders = ",".join("?" for _ in allowed_ids)
        candidates: list[ChunkSearchHit] = []
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    f"""
                    SELECT chunks.*, chunk_embeddings.dimensions,
                        chunk_embeddings.vector
                    FROM chunk_embeddings
                    JOIN chunks ON chunks.chunk_id = chunk_embeddings.chunk_id
                    WHERE chunk_embeddings.model_name = ?
                        AND chunks.chunk_version = ?
                        AND chunks.resource_id IN ({placeholders})
                    """,
                    [embedding_model, chunk_version, *allowed_ids],
                )
                for row in rows:
                    dimensions = int(row["dimensions"])
                    if dimensions != len(vector):
                        continue
                    stored = struct.unpack(f"<{dimensions}f", row["vector"])
                    cosine = sum(left * right for left, right in zip(vector, stored))
                    score = max(0.0, min(1.0, (cosine + 1.0) / 2.0))
                    candidates.append(
                        ChunkSearchHit(chunk=self._chunk(row), score=score)
                    )
                    if len(candidates) > limit:
                        candidates.sort(
                            key=lambda hit: (-hit.score, hit.chunk.chunk_id)
                        )
                        del candidates[limit:]
            candidates.sort(key=lambda hit: (-hit.score, hit.chunk.chunk_id))
            return candidates
        except (sqlite3.Error, struct.error) as exc:
            raise ResourceStoreError("Could not search semantic chunk vectors.") from exc

    def cached_extraction(
        self, resource_id: str, extraction_version: str
    ) -> list[dict[str, object]] | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT extraction_json FROM resources
                    WHERE resource_id = ? AND status IN ('ready', 'processing')
                        AND extraction_version = ?
                    """,
                    (resource_id, extraction_version),
                ).fetchone()
            if row is None or row["extraction_json"] is None:
                return None
            value = json.loads(row["extraction_json"])
            if not isinstance(value, list):
                raise ResourceStoreError("Cached extraction has an invalid shape.")
            return value
        except (sqlite3.Error, json.JSONDecodeError) as exc:
            raise ResourceStoreError("Could not read cached extracted content.") from exc

    def enqueue_extraction(
        self,
        resource_id: str,
        pipeline_version: str,
        *,
        retry_failed: bool = False,
    ) -> ProcessingJob:
        """Create one durable extraction job per resource, or explicitly retry it."""
        now = datetime.now(UTC).isoformat()
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                resource = connection.execute(
                    "SELECT * FROM resources WHERE resource_id = ?", (resource_id,)
                ).fetchone()
                if resource is None:
                    raise ResourceStoreError("Resource metadata was not found.")

                existing = connection.execute(
                    "SELECT * FROM processing_jobs WHERE resource_id = ?",
                    (resource_id,),
                ).fetchone()
                cached_for_version = (
                    resource["status"] == "ready"
                    and resource["extraction_json"] is not None
                    and resource["extraction_version"] == pipeline_version
                )

                if existing is None:
                    status = "completed" if cached_for_version else "queued"
                    completed_at = now if cached_for_version else None
                    connection.execute(
                        """
                        INSERT INTO processing_jobs (
                            job_id, resource_id, pipeline_version, status,
                            attempts, progress_current, progress_total, error,
                            created_at, updated_at, started_at, completed_at
                        ) VALUES (?, ?, ?, ?, 0, 0, NULL, NULL, ?, ?, NULL, ?)
                        """,
                        (
                            uuid.uuid4().hex,
                            resource_id,
                            pipeline_version,
                            status,
                            now,
                            now,
                            completed_at,
                        ),
                    )
                elif cached_for_version:
                    connection.execute(
                        """
                        UPDATE processing_jobs
                        SET pipeline_version = ?, status = 'completed', error = NULL,
                            updated_at = ?, completed_at = ?
                        WHERE resource_id = ?
                        """,
                        (pipeline_version, now, now, resource_id),
                    )
                elif (
                    existing["pipeline_version"] != pipeline_version
                    or (existing["status"] == "failed" and retry_failed)
                ):
                    connection.execute(
                        """
                        UPDATE processing_jobs
                        SET pipeline_version = ?, status = 'queued', attempts = 0,
                            progress_current = 0, progress_total = NULL, error = NULL,
                            updated_at = ?, started_at = NULL, completed_at = NULL
                        WHERE resource_id = ?
                        """,
                        (pipeline_version, now, resource_id),
                    )
                    connection.execute(
                        """
                        UPDATE resources
                        SET status = 'uploaded', error = NULL, updated_at = ?
                        WHERE resource_id = ?
                        """,
                        (now, resource_id),
                    )

                row = connection.execute(
                    "SELECT * FROM processing_jobs WHERE resource_id = ?",
                    (resource_id,),
                ).fetchone()
            job = self._job(row)
            if job is None:
                raise ResourceStoreError("Could not queue resource processing.")
            return job
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not queue resource processing.") from exc

    def get_extraction_job(self, resource_id: str) -> ProcessingJob | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM processing_jobs WHERE resource_id = ?",
                    (resource_id,),
                ).fetchone()
            return self._job(row)
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not read processing status.") from exc

    def claim_next_extraction(self) -> ProcessingJob | None:
        """Atomically claim work while allowing at most one processing job."""
        now = datetime.now(UTC).isoformat()
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                active = connection.execute(
                    "SELECT 1 FROM processing_jobs WHERE status = 'processing' LIMIT 1"
                ).fetchone()
                if active is not None:
                    return None
                row = connection.execute(
                    """
                    SELECT * FROM processing_jobs
                    WHERE status = 'queued'
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                ).fetchone()
                if row is None:
                    return None
                connection.execute(
                    """
                    UPDATE processing_jobs
                    SET status = 'processing', attempts = attempts + 1,
                        progress_current = 0, progress_total = NULL, error = NULL,
                        updated_at = ?, started_at = ?, completed_at = NULL
                    WHERE job_id = ?
                    """,
                    (now, now, row["job_id"]),
                )
                connection.execute(
                    """
                    UPDATE resources
                    SET status = 'processing', error = NULL, updated_at = ?
                    WHERE resource_id = ?
                    """,
                    (now, row["resource_id"]),
                )
                claimed = connection.execute(
                    "SELECT * FROM processing_jobs WHERE job_id = ?",
                    (row["job_id"],),
                ).fetchone()
            return self._job(claimed)
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not claim queued processing work.") from exc

    def update_job_progress(self, job_id: str, current: int, total: int) -> None:
        if current < 0 or total <= 0 or current > total:
            raise ValueError("Invalid processing progress.")
        now = datetime.now(UTC).isoformat()
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE processing_jobs
                    SET progress_current = ?, progress_total = ?, updated_at = ?
                    WHERE job_id = ? AND status = 'processing'
                    """,
                    (current, total, now, job_id),
                )
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not update processing progress.") from exc

    def complete_job(self, job_id: str) -> None:
        now = datetime.now(UTC).isoformat()
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE processing_jobs
                    SET status = 'completed', error = NULL, updated_at = ?,
                        completed_at = ?, progress_current = CASE
                            WHEN progress_total IS NULL THEN progress_current
                            ELSE progress_total
                        END
                    WHERE job_id = ? AND status = 'processing'
                    """,
                    (now, now, job_id),
                )
            if cursor.rowcount != 1:
                raise ResourceStoreError("Processing job was not active.")
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not complete processing work.") from exc

    def fail_job(self, job_id: str, resource_id: str, error: str) -> None:
        now = datetime.now(UTC).isoformat()
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    UPDATE processing_jobs
                    SET status = 'failed', error = ?, updated_at = ?, completed_at = ?
                    WHERE job_id = ?
                    """,
                    (error, now, now, job_id),
                )
                connection.execute(
                    """
                    UPDATE resources
                    SET status = 'failed', error = ?, updated_at = ?
                    WHERE resource_id = ?
                    """,
                    (error, now, resource_id),
                )
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not record processing failure.") from exc

    def recover_interrupted_jobs(self, stale_after_seconds: int) -> int:
        """Requeue jobs whose worker stopped updating them before the cutoff."""
        cutoff = (datetime.now(UTC) - timedelta(seconds=stale_after_seconds)).isoformat()
        now = datetime.now(UTC).isoformat()
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                rows = connection.execute(
                    """
                    SELECT resource_id FROM processing_jobs
                    WHERE status = 'processing' AND updated_at < ?
                    """,
                    (cutoff,),
                ).fetchall()
                resource_ids = [row["resource_id"] for row in rows]
                connection.execute(
                    """
                    UPDATE processing_jobs
                    SET status = 'queued', error = 'Interrupted processing was resumed.',
                        progress_current = 0, progress_total = NULL,
                        updated_at = ?, started_at = NULL, completed_at = NULL
                    WHERE status = 'processing' AND updated_at < ?
                    """,
                    (now, cutoff),
                )
                connection.executemany(
                    """
                    UPDATE resources
                    SET status = 'uploaded', error = NULL, updated_at = ?
                    WHERE resource_id = ?
                    """,
                    [(now, resource_id) for resource_id in resource_ids],
                )
            return len(resource_ids)
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not recover interrupted processing.") from exc
