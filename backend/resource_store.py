"""SQLite-backed material metadata and extraction cache."""
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3


VALID_STATUSES = {"uploaded", "processing", "ready", "failed"}


class ResourceStoreError(RuntimeError):
    """A safe boundary for local metadata persistence failures."""


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

    def cached_extraction(
        self, resource_id: str, extraction_version: str
    ) -> list[dict[str, object]] | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT extraction_json FROM resources
                    WHERE resource_id = ? AND status = 'ready'
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
