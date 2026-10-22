"""SQLite-backed material metadata, extraction cache, and local indexes."""
from __future__ import annotations

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


class ResourceProcessingError(ResourceStoreError):
    """A resource cannot be deleted while its worker is processing it."""


class MonthlyUsageLimitError(ResourceStoreError):
    """A locally enforced monthly external-service limit was reached."""


@dataclass(frozen=True)
class UserRecord:
    user_id: str
    email: str
    display_name: str
    role: str
    password_hash: str
    password_salt: str
    created_at: str
    last_seen_at: str
    active_seconds: int
    disabled: bool

    def public_dict(self) -> dict[str, object]:
        return {
            "user_id": self.user_id,
            "email": self.email,
            "display_name": self.display_name,
            "role": self.role,
        }


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
    source_url: str | None = None
    thumbnail_url: str | None = None

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
class QuizAttemptRecord:
    quiz_id: str
    owner_user_id: str | None
    session_id: str
    source_ids: list[str]
    questions: list[dict[str, object]]
    status: str
    answers: list[dict[str, object]] | None
    score: int | None
    created_at: str
    submitted_at: str | None


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
            if "source_url" not in columns:
                connection.execute(
                    "ALTER TABLE resources ADD COLUMN source_url TEXT"
                )
            if "thumbnail_url" not in columns:
                connection.execute(
                    "ALTER TABLE resources ADD COLUMN thumbnail_url TEXT"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_resources_updated_at "
                "ON resources(updated_at DESC)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    display_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'admin')),
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    active_seconds INTEGER NOT NULL DEFAULT 0
                        CHECK (active_seconds >= 0),
                    disabled INTEGER NOT NULL DEFAULT 0
                        CHECK (disabled IN (0, 1))
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                        ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_auth_sessions_user "
                "ON auth_sessions(user_id, expires_at)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_resources (
                    user_id TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    linked_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, resource_id),
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                        ON DELETE CASCADE,
                    FOREIGN KEY(resource_id) REFERENCES resources(resource_id)
                        ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_resources_resource "
                "ON user_resources(resource_id)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_ai_usage (
                    user_id TEXT NOT NULL,
                    period TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL DEFAULT 0
                        CHECK (input_tokens >= 0),
                    output_tokens INTEGER NOT NULL DEFAULT 0
                        CHECK (output_tokens >= 0),
                    chat_requests INTEGER NOT NULL DEFAULT 0
                        CHECK (chat_requests >= 0),
                    quiz_requests INTEGER NOT NULL DEFAULT 0
                        CHECK (quiz_requests >= 0),
                    summary_requests INTEGER NOT NULL DEFAULT 0
                        CHECK (summary_requests >= 0),
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, period),
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                        ON DELETE CASCADE
                )
                """
            )
            usage_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(user_ai_usage)").fetchall()
            }
            if "summary_requests" not in usage_columns:
                connection.execute(
                    "ALTER TABLE user_ai_usage ADD COLUMN summary_requests "
                    "INTEGER NOT NULL DEFAULT 0 CHECK (summary_requests >= 0)"
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
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    session_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    source_ids_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            chat_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(chat_sessions)").fetchall()
            }
            if "owner_user_id" not in chat_columns:
                connection.execute(
                    "ALTER TABLE chat_sessions ADD COLUMN owner_user_id TEXT"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated_at "
                "ON chat_sessions(updated_at DESC)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_messages (
                    message_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    citations_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES chat_sessions(session_id)
                        ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created "
                "ON chat_messages(session_id, created_at)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS quiz_attempts (
                    quiz_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    source_ids_json TEXT NOT NULL,
                    questions_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('ready', 'submitted')),
                    answers_json TEXT,
                    score INTEGER,
                    created_at TEXT NOT NULL,
                    submitted_at TEXT
                )
                """
            )
            quiz_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(quiz_attempts)").fetchall()
            }
            if "owner_user_id" not in quiz_columns:
                connection.execute(
                    "ALTER TABLE quiz_attempts ADD COLUMN owner_user_id TEXT"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_quiz_attempts_session_created "
                "ON quiz_attempts(session_id, created_at DESC)"
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
                    start_seconds REAL,
                    end_seconds REAL,
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
            chunk_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(chunks)").fetchall()
            }
            if "start_seconds" not in chunk_columns:
                connection.execute("ALTER TABLE chunks ADD COLUMN start_seconds REAL")
            if "end_seconds" not in chunk_columns:
                connection.execute("ALTER TABLE chunks ADD COLUMN end_seconds REAL")
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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS interview_sessions (
                    interview_id TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    job_role TEXT NOT NULL,
                    job_description TEXT NOT NULL DEFAULT '',
                    resume_text TEXT NOT NULL DEFAULT '',
                    material_context TEXT NOT NULL DEFAULT '',
                    question_count INTEGER NOT NULL DEFAULT 5,
                    interview_type TEXT NOT NULL DEFAULT 'mixed',
                    system_prompt TEXT NOT NULL DEFAULT '',
                    history_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'active',
                    report_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_interview_sessions_owner_updated "
                "ON interview_sessions(owner_user_id, updated_at DESC)"
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
            source_url=row["source_url"],
            thumbnail_url=row["thumbnail_url"],
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
            start_seconds=row["start_seconds"],
            end_seconds=row["end_seconds"],
        )

    @staticmethod
    def _user(row: sqlite3.Row | None) -> UserRecord | None:
        if row is None:
            return None
        return UserRecord(
            user_id=row["user_id"],
            email=row["email"],
            display_name=row["display_name"],
            role=row["role"],
            password_hash=row["password_hash"],
            password_salt=row["password_salt"],
            created_at=row["created_at"],
            last_seen_at=row["last_seen_at"],
            active_seconds=int(row["active_seconds"]),
            disabled=bool(row["disabled"]),
        )

    def create_user(
        self,
        *,
        email: str,
        display_name: str,
        password_hash: str,
        password_salt: str,
        role: str = "user",
    ) -> UserRecord:
        if role not in {"user", "admin"}:
            raise ValueError("Invalid user role.")
        now = datetime.now(UTC).isoformat()
        user_id = uuid.uuid4().hex
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO users (
                        user_id, email, display_name, password_hash,
                        password_salt, role, created_at, last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        email.casefold(),
                        display_name,
                        password_hash,
                        password_salt,
                        role,
                        now,
                        now,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM users WHERE user_id = ?", (user_id,)
                ).fetchone()
            user = self._user(row)
            if user is None:
                raise ResourceStoreError("Could not create the user account.")
            return user
        except sqlite3.IntegrityError as exc:
            raise ResourceStoreError("An account with this email already exists.") from exc
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not create the user account.") from exc

    def upsert_admin(
        self,
        *,
        email: str,
        display_name: str,
        password_hash: str,
        password_salt: str,
    ) -> UserRecord:
        now = datetime.now(UTC).isoformat()
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO users (
                        user_id, email, display_name, password_hash,
                        password_salt, role, created_at, last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, 'admin', ?, ?)
                    ON CONFLICT(email) DO UPDATE SET
                        display_name = excluded.display_name,
                        password_hash = excluded.password_hash,
                        password_salt = excluded.password_salt,
                        role = 'admin',
                        disabled = 0
                    """,
                    (
                        uuid.uuid4().hex,
                        email.casefold(),
                        display_name,
                        password_hash,
                        password_salt,
                        now,
                        now,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM users WHERE email = ? COLLATE NOCASE",
                    (email.casefold(),),
                ).fetchone()
            user = self._user(row)
            if user is None:
                raise ResourceStoreError("Could not configure the admin account.")
            return user
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not configure the admin account.") from exc

    def get_user_by_email(self, email: str) -> UserRecord | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM users WHERE email = ? COLLATE NOCASE",
                    (email.casefold(),),
                ).fetchone()
            return self._user(row)
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not read the user account.") from exc

    def create_auth_session(
        self, user_id: str, token_hash: str, expires_at: str
    ) -> None:
        now = datetime.now(UTC).isoformat()
        try:
            with self._connect() as connection:
                connection.execute(
                    "DELETE FROM auth_sessions WHERE expires_at <= ?", (now,)
                )
                connection.execute(
                    """
                    INSERT INTO auth_sessions (
                        token_hash, user_id, created_at, expires_at, last_seen_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (token_hash, user_id, now, expires_at, now),
                )
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not create the login session.") from exc

    def resolve_auth_session(self, token_hash: str) -> UserRecord | None:
        now = datetime.now(UTC)
        now_text = now.isoformat()
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """
                    SELECT users.*, auth_sessions.last_seen_at AS session_last_seen
                    FROM auth_sessions
                    JOIN users ON users.user_id = auth_sessions.user_id
                    WHERE auth_sessions.token_hash = ?
                        AND auth_sessions.expires_at > ?
                        AND users.disabled = 0
                    """,
                    (token_hash, now_text),
                ).fetchone()
                if row is None:
                    return None
                try:
                    previous = datetime.fromisoformat(row["session_last_seen"])
                    elapsed = max(0, int((now - previous).total_seconds()))
                except (TypeError, ValueError):
                    elapsed = 0
                active_increment = elapsed if elapsed <= 300 else 0
                connection.execute(
                    "UPDATE auth_sessions SET last_seen_at = ? WHERE token_hash = ?",
                    (now_text, token_hash),
                )
                connection.execute(
                    """
                    UPDATE users
                    SET last_seen_at = ?, active_seconds = active_seconds + ?
                    WHERE user_id = ?
                    """,
                    (now_text, active_increment, row["user_id"]),
                )
                refreshed = connection.execute(
                    "SELECT * FROM users WHERE user_id = ?", (row["user_id"],)
                ).fetchone()
            return self._user(refreshed)
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not validate the login session.") from exc

    def delete_auth_session(self, token_hash: str) -> bool:
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    "DELETE FROM auth_sessions WHERE token_hash = ?", (token_hash,)
                )
            return cursor.rowcount > 0
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not end the login session.") from exc

    def claim_legacy_data(self, user_id: str) -> None:
        """Assign pre-authentication local data to the configured admin."""
        now = datetime.now(UTC).isoformat()
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT OR IGNORE INTO user_resources (user_id, resource_id, linked_at)
                    SELECT ?, resource_id, ? FROM resources
                    WHERE NOT EXISTS (
                        SELECT 1 FROM user_resources
                        WHERE user_resources.resource_id = resources.resource_id
                    )
                    """,
                    (user_id, now),
                )
                connection.execute(
                    "UPDATE chat_sessions SET owner_user_id = ? WHERE owner_user_id IS NULL",
                    (user_id,),
                )
                connection.execute(
                    "UPDATE quiz_attempts SET owner_user_id = ? WHERE owner_user_id IS NULL",
                    (user_id,),
                )
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not assign existing local data.") from exc

    def link_user_resource(self, user_id: str, resource_id: str) -> None:
        now = datetime.now(UTC).isoformat()
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO user_resources (user_id, resource_id, linked_at)
                    VALUES (?, ?, ?)
                    """,
                    (user_id, resource_id, now),
                )
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not link the material to this account.") from exc

    def user_has_resource(self, user_id: str, resource_id: str) -> bool:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT 1 FROM user_resources
                    WHERE user_id = ? AND resource_id = ?
                    """,
                    (user_id, resource_id),
                ).fetchone()
            return row is not None
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not verify material access.") from exc

    def unlink_user_resource(self, user_id: str, resource_id: str) -> tuple[bool, bool]:
        """Return (link_removed, resource_has_no_remaining_users)."""
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    """
                    DELETE FROM user_resources
                    WHERE user_id = ? AND resource_id = ?
                    """,
                    (user_id, resource_id),
                )
                remaining = connection.execute(
                    "SELECT COUNT(*) AS count FROM user_resources WHERE resource_id = ?",
                    (resource_id,),
                ).fetchone()
            return cursor.rowcount > 0, int(remaining["count"]) == 0
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not remove material access.") from exc

    def list_for_user(self, user_id: str) -> list[ResourceRecord]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT resources.* FROM resources
                    JOIN user_resources
                        ON user_resources.resource_id = resources.resource_id
                    WHERE user_resources.user_id = ?
                    ORDER BY resources.updated_at DESC
                    """,
                    (user_id,),
                ).fetchall()
            return [record for row in rows if (record := self._record(row))]
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not list account materials.") from exc

    def record_user_ai_usage(
        self,
        user_id: str,
        *,
        input_tokens: int,
        output_tokens: int,
        operation: str,
    ) -> None:
        period = datetime.now(UTC).strftime("%Y-%m")
        now = datetime.now(UTC).isoformat()
        chat_increment = 1 if operation == "chat" else 0
        quiz_increment = 1 if operation == "quiz" else 0
        summary_increment = 1 if operation == "summary" else 0
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO user_ai_usage (
                        user_id, period, input_tokens, output_tokens,
                        chat_requests, quiz_requests, summary_requests, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, period) DO UPDATE SET
                        input_tokens = input_tokens + excluded.input_tokens,
                        output_tokens = output_tokens + excluded.output_tokens,
                        chat_requests = chat_requests + excluded.chat_requests,
                        quiz_requests = quiz_requests + excluded.quiz_requests,
                        summary_requests = summary_requests + excluded.summary_requests,
                        updated_at = excluded.updated_at
                    """,
                    (
                        user_id,
                        period,
                        max(0, input_tokens),
                        max(0, output_tokens),
                        chat_increment,
                        quiz_increment,
                        summary_increment,
                        now,
                    ),
                )
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not record account usage.") from exc

    def list_admin_user_metrics(self) -> list[dict[str, object]]:
        period = datetime.now(UTC).strftime("%Y-%m")
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT users.user_id, users.role,
                        users.created_at, users.last_seen_at, users.active_seconds,
                        COALESCE(SUM(resources.size_bytes), 0) AS storage_bytes,
                        COUNT(DISTINCT resources.resource_id) AS material_count,
                        COALESCE(usage.input_tokens, 0) AS input_tokens,
                        COALESCE(usage.output_tokens, 0) AS output_tokens,
                        COALESCE(usage.chat_requests, 0) AS chat_requests,
                        COALESCE(usage.quiz_requests, 0) AS quiz_requests,
                        COALESCE(usage.summary_requests, 0) AS summary_requests
                    FROM users
                    LEFT JOIN user_resources ON user_resources.user_id = users.user_id
                    LEFT JOIN resources ON resources.resource_id = user_resources.resource_id
                    LEFT JOIN user_ai_usage AS usage
                        ON usage.user_id = users.user_id AND usage.period = ?
                    WHERE users.disabled = 0
                    GROUP BY users.user_id
                    ORDER BY users.created_at ASC
                    """,
                    (period,),
                ).fetchall()
                domain_rows = connection.execute(
                    """
                    SELECT user_resources.user_id, resources.source_type,
                        COUNT(*) AS count
                    FROM user_resources
                    JOIN resources ON resources.resource_id = user_resources.resource_id
                    GROUP BY user_resources.user_id, resources.source_type
                    """
                ).fetchall()
            domains: dict[str, list[dict[str, object]]] = {}
            for row in domain_rows:
                label = {
                    "pdf": "Documents",
                    "pptx": "Presentations",
                    "image": "Images",
                    "video": "Video learning",
                }.get(row["source_type"], "Other")
                domains.setdefault(row["user_id"], []).append(
                    {"label": label, "count": int(row["count"])}
                )
            results: list[dict[str, object]] = []
            for row in rows:
                results.append(
                    {
                        "user_id": row["user_id"],
                        "display_name": f"Learner {row['user_id'][:8]}",
                        "email_hint": "Private account",
                        "role": row["role"],
                        "created_at": row["created_at"],
                        "last_seen_at": row["last_seen_at"],
                        "active_seconds": int(row["active_seconds"]),
                        "storage_bytes": int(row["storage_bytes"]),
                        "material_count": int(row["material_count"]),
                        "input_tokens": int(row["input_tokens"]),
                        "output_tokens": int(row["output_tokens"]),
                        "chat_requests": int(row["chat_requests"]),
                        "quiz_requests": int(row["quiz_requests"]),
                        "summary_requests": int(row["summary_requests"]),
                        "explored_domains": domains.get(row["user_id"], []),
                    }
                )
            return results
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not load admin usage metrics.") from exc

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
        source_url: str | None = None,
        thumbnail_url: str | None = None,
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
                            created_at, updated_at, source_url, thumbnail_url
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'uploaded', NULL, NULL, NULL, ?, ?, ?, ?)
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
                            source_url,
                            thumbnail_url,
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

    def update_resource_display(
        self,
        resource_id: str,
        *,
        original_filename: str,
        thumbnail_url: str | None,
    ) -> ResourceRecord:
        now = datetime.now(UTC).isoformat()
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE resources
                    SET original_filename = ?, thumbnail_url = ?, updated_at = ?
                    WHERE resource_id = ?
                    """,
                    (original_filename, thumbnail_url, now, resource_id),
                )
                row = connection.execute(
                    "SELECT * FROM resources WHERE resource_id = ?", (resource_id,)
                ).fetchone()
            record = self._record(row)
            if record is None:
                raise ResourceStoreError("Could not update resource metadata.")
            return record
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not update resource metadata.") from exc

    def delete(self, resource_id: str, *, reject_processing: bool = False) -> bool:
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT status FROM resources WHERE resource_id = ?",
                    (resource_id,),
                ).fetchone()
                if row is None:
                    return False
                if reject_processing and row["status"] == "processing":
                    raise ResourceProcessingError(
                        "This material is processing. Wait for it to finish before deleting it."
                    )
                connection.execute(
                    "DELETE FROM chunks_fts WHERE resource_id = ?", (resource_id,)
                )
                connection.execute(
                    "DELETE FROM resources WHERE resource_id = ?", (resource_id,)
                )
            return True
        except ResourceProcessingError:
            raise
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not remove stale resource metadata.") from exc

    def append_chat_turn(
        self,
        owner_user_id: str,
        session_id: str,
        question: str,
        answer: str,
        source_ids: Sequence[str],
        citations: Sequence[Mapping[str, object]],
    ) -> None:
        """Persist one completed learner question and its grounded answer."""
        now = datetime.now(UTC).isoformat()
        title = question.strip().replace("\n", " ")[:120] or "Learning chat"
        normalized_sources = list(dict.fromkeys(source_ids))
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO chat_sessions (
                        session_id, title, source_ids_json, created_at, updated_at,
                        owner_user_id
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        source_ids_json = excluded.source_ids_json,
                        updated_at = excluded.updated_at
                    WHERE chat_sessions.owner_user_id = excluded.owner_user_id
                    """,
                    (
                        session_id,
                        title,
                        json.dumps(normalized_sources),
                        now,
                        now,
                        owner_user_id,
                    ),
                )
                owned = connection.execute(
                    """
                    SELECT 1 FROM chat_sessions
                    WHERE session_id = ? AND owner_user_id = ?
                    """,
                    (session_id, owner_user_id),
                ).fetchone()
                if owned is None:
                    raise ResourceStoreError("Chat session belongs to another account.")
                connection.executemany(
                    """
                    INSERT INTO chat_messages (
                        message_id, session_id, role, content, citations_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (uuid.uuid4().hex, session_id, "user", question, "[]", now),
                        (
                            uuid.uuid4().hex,
                            session_id,
                            "assistant",
                            answer,
                            json.dumps(list(citations)),
                            now,
                        ),
                    ],
                )
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not save chat history.") from exc

    def list_chat_sessions(self, owner_user_id: str) -> list[dict[str, object]]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT sessions.*,
                        (SELECT COUNT(*) FROM chat_messages
                         WHERE chat_messages.session_id = sessions.session_id) AS message_count
                    FROM chat_sessions AS sessions
                    WHERE sessions.owner_user_id = ?
                    ORDER BY updated_at DESC
                    LIMIT 100
                    """,
                    (owner_user_id,),
                ).fetchall()
            return [
                {
                    "session_id": row["session_id"],
                    "title": row["title"],
                    "source_ids": json.loads(row["source_ids_json"]),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "message_count": row["message_count"],
                }
                for row in rows
            ]
        except (sqlite3.Error, ValueError, TypeError) as exc:
            raise ResourceStoreError("Could not list chat history.") from exc

    def get_chat_session(
        self, session_id: str, owner_user_id: str
    ) -> dict[str, object] | None:
        try:
            with self._connect() as connection:
                session = connection.execute(
                    """
                    SELECT * FROM chat_sessions
                    WHERE session_id = ? AND owner_user_id = ?
                    """,
                    (session_id, owner_user_id),
                ).fetchone()
                if session is None:
                    return None
                messages = connection.execute(
                    """
                    SELECT message_id, role, content, citations_json, created_at
                    FROM chat_messages WHERE session_id = ?
                    ORDER BY created_at ASC, message_id ASC
                    """,
                    (session_id,),
                ).fetchall()
            return {
                "session_id": session["session_id"],
                "title": session["title"],
                "source_ids": json.loads(session["source_ids_json"]),
                "created_at": session["created_at"],
                "updated_at": session["updated_at"],
                "messages": [
                    {
                        "message_id": row["message_id"],
                        "role": row["role"],
                        "content": row["content"],
                        "citations": json.loads(row["citations_json"]),
                        "created_at": row["created_at"],
                    }
                    for row in messages
                ],
            }
        except (sqlite3.Error, ValueError, TypeError) as exc:
            raise ResourceStoreError("Could not read chat history.") from exc

    def get_recent_chat_turns(
        self,
        session_id: str,
        owner_user_id: str,
        *,
        limit: int = 8,
        source_ids: Sequence[str] | None = None,
    ) -> list[dict[str, str]]:
        """Return bounded, server-owned context for follow-up questions."""
        bounded_limit = max(1, min(12, limit))
        try:
            with self._connect() as connection:
                owned = connection.execute(
                    """
                    SELECT source_ids_json FROM chat_sessions
                    WHERE session_id = ? AND owner_user_id = ?
                    """,
                    (session_id, owner_user_id),
                ).fetchone()
                if owned is None:
                    return []
                if source_ids is not None:
                    saved_sources = set(json.loads(owned["source_ids_json"]))
                    if saved_sources != set(source_ids):
                        return []
                rows = connection.execute(
                    """
                    SELECT role, content FROM chat_messages
                    WHERE session_id = ?
                    ORDER BY created_at DESC, message_id DESC
                    LIMIT ?
                    """,
                    (session_id, bounded_limit),
                ).fetchall()
            return [
                {"role": row["role"], "content": str(row["content"])[:4_000]}
                for row in reversed(rows)
                if row["role"] in {"user", "assistant"}
            ]
        except (sqlite3.Error, json.JSONDecodeError, TypeError) as exc:
            raise ResourceStoreError("Could not read conversational context.") from exc

    def delete_chat_session(self, session_id: str, owner_user_id: str) -> bool:
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    DELETE FROM chat_sessions
                    WHERE session_id = ? AND owner_user_id = ?
                    """,
                    (session_id, owner_user_id),
                )
            return cursor.rowcount > 0
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not delete chat history.") from exc

    @staticmethod
    def _quiz_attempt(row: sqlite3.Row | None) -> QuizAttemptRecord | None:
        if row is None:
            return None
        try:
            return QuizAttemptRecord(
                quiz_id=row["quiz_id"],
                owner_user_id=row["owner_user_id"],
                session_id=row["session_id"],
                source_ids=json.loads(row["source_ids_json"]),
                questions=json.loads(row["questions_json"]),
                status=row["status"],
                answers=(
                    json.loads(row["answers_json"])
                    if row["answers_json"] is not None
                    else None
                ),
                score=row["score"],
                created_at=row["created_at"],
                submitted_at=row["submitted_at"],
            )
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            raise ResourceStoreError("Stored quiz data is invalid.") from exc

    def create_quiz_attempt(
        self,
        quiz_id: str,
        owner_user_id: str,
        session_id: str,
        source_ids: list[str],
        questions: list[dict[str, object]],
    ) -> QuizAttemptRecord:
        now = datetime.now(UTC).isoformat()
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO quiz_attempts (
                        quiz_id, session_id, source_ids_json, questions_json,
                        status, answers_json, score, created_at, submitted_at,
                        owner_user_id
                    ) VALUES (?, ?, ?, ?, 'ready', NULL, NULL, ?, NULL, ?)
                    """,
                    (
                        quiz_id,
                        session_id,
                        json.dumps(list(dict.fromkeys(source_ids))),
                        json.dumps(questions),
                        now,
                        owner_user_id,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM quiz_attempts WHERE quiz_id = ?", (quiz_id,)
                ).fetchone()
            attempt = self._quiz_attempt(row)
            if attempt is None:
                raise ResourceStoreError("Could not save generated quiz.")
            return attempt
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not save generated quiz.") from exc

    def get_quiz_attempt(
        self, quiz_id: str, owner_user_id: str
    ) -> QuizAttemptRecord | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT * FROM quiz_attempts
                    WHERE quiz_id = ? AND owner_user_id = ?
                    """,
                    (quiz_id, owner_user_id),
                ).fetchone()
            return self._quiz_attempt(row)
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not read generated quiz.") from exc

    def complete_quiz_attempt(
        self,
        quiz_id: str,
        owner_user_id: str,
        answers: list[dict[str, object]],
        score: int,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE quiz_attempts
                    SET status = 'submitted', answers_json = ?, score = ?,
                        submitted_at = ?
                    WHERE quiz_id = ? AND owner_user_id = ? AND status = 'ready'
                    """,
                    (json.dumps(answers), score, now, quiz_id, owner_user_id),
                )
            if cursor.rowcount != 1:
                raise ResourceStoreError("Quiz was already submitted or was not found.")
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not save quiz result.") from exc

    def list_quiz_attempts(self, owner_user_id: str) -> list[QuizAttemptRecord]:
        """Return one account's quiz records for its portable data export."""
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT * FROM quiz_attempts
                    WHERE owner_user_id = ?
                    ORDER BY created_at ASC, quiz_id ASC
                    """,
                    (owner_user_id,),
                ).fetchall()
            return [attempt for row in rows if (attempt := self._quiz_attempt(row))]
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not read quiz history.") from exc

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
                chunk_version, start_seconds, end_seconds, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    chunk.start_seconds,
                    chunk.end_seconds,
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

    def saved_extraction(
        self, resource_id: str
    ) -> list[dict[str, object]] | None:
        """Read persisted extraction for History even if its pipeline is now older."""
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT extraction_json FROM resources
                    WHERE resource_id = ? AND status IN ('ready', 'processing')
                    """,
                    (resource_id,),
                ).fetchone()
            if row is None or row["extraction_json"] is None:
                return None
            value = json.loads(row["extraction_json"])
            if not isinstance(value, list):
                raise ResourceStoreError("Cached extraction has an invalid shape.")
            return value
        except (sqlite3.Error, json.JSONDecodeError) as exc:
            raise ResourceStoreError("Could not read saved extracted content.") from exc

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

    # ------------------------------------------------------------------
    # Interview session persistence
    # ------------------------------------------------------------------

    def save_interview_session(
        self,
        *,
        interview_id: str,
        user_id: str,
        session_id: str,
        job_role: str,
        job_description: str,
        resume_text: str,
        material_context: str,
        question_count: int,
        interview_type: str,
        system_prompt: str,
        history: list,
        status: str,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO interview_sessions (
                        interview_id, owner_user_id, session_id, job_role,
                        job_description, resume_text, material_context,
                        question_count, interview_type, system_prompt,
                        history_json, status, created_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        interview_id, user_id, session_id, job_role,
                        job_description, resume_text, material_context,
                        question_count, interview_type, system_prompt,
                        json.dumps(history), status, now, now,
                    ),
                )
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not save interview session.") from exc

    def get_interview_session(self, interview_id: str, user_id: str) -> dict | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM interview_sessions WHERE interview_id=? AND owner_user_id=?",
                    (interview_id, user_id),
                ).fetchone()
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not fetch interview session.") from exc
        if row is None:
            return None
        return {
            "interview_id": row["interview_id"],
            "session_id": row["session_id"],
            "job_role": row["job_role"],
            "job_description": row["job_description"],
            "resume_text": row["resume_text"],
            "material_context": row["material_context"],
            "question_count": row["question_count"],
            "interview_type": row["interview_type"],
            "system_prompt": row["system_prompt"],
            "history": json.loads(row["history_json"] or "[]"),
            "status": row["status"],
            "report": json.loads(row["report_json"]) if row["report_json"] else None,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def update_interview_session(
        self,
        *,
        interview_id: str,
        user_id: str,
        history: list,
        status: str,
        report: dict | None = None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE interview_sessions
                    SET history_json=?, status=?, report_json=?, updated_at=?
                    WHERE interview_id=? AND owner_user_id=?
                    """,
                    (
                        json.dumps(history),
                        status,
                        json.dumps(report) if report is not None else None,
                        now,
                        interview_id,
                        user_id,
                    ),
                )
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not update interview session.") from exc

    def list_interview_sessions(self, user_id: str) -> list[dict]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT interview_id, job_role, interview_type, question_count,
                           status, created_at, updated_at
                    FROM interview_sessions
                    WHERE owner_user_id=?
                    ORDER BY updated_at DESC
                    LIMIT 50
                    """,
                    (user_id,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not list interview sessions.") from exc
        return [
            {
                "interview_id": row["interview_id"],
                "job_role": row["job_role"],
                "interview_type": row["interview_type"],
                "question_count": row["question_count"],
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def delete_interview_session(self, interview_id: str, user_id: str) -> None:
        try:
            with self._connect() as connection:
                connection.execute(
                    "DELETE FROM interview_sessions WHERE interview_id=? AND owner_user_id=?",
                    (interview_id, user_id),
                )
        except sqlite3.Error as exc:
            raise ResourceStoreError("Could not delete interview session.") from exc
