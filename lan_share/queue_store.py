from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
import re
import sqlite3
import time
import unicodedata
from urllib.parse import urlparse

from lan_share.indexer import normalize_search_text


QUEUE_STATUSES = (
    "pending",
    "processing",
    "completed",
    "retry",
    "paid_skipped",
    "not_found_skipped",
    "manual_ios",
    "manual_paid",
    "manual_not_found",
)
RUNNABLE_STATUSES = ("pending", "retry")
ACTIVE_STATUSES = ("pending", "processing", "retry")
SEARCH_MISS_LIMIT = 1
SKIPPED_STATUSES = ("paid_skipped", "not_found_skipped")
MANUAL_STATUSES = ("manual_ios", "manual_paid", "manual_not_found")
MANUAL_CATEGORY_STATUSES = {
    "ios": "manual_ios",
    "paid": "manual_paid",
    "not_found": "manual_not_found",
}


@dataclass(frozen=True)
class KeywordJob:
    id: int
    keyword: str
    status: str
    attempt_count: int
    search_miss_count: int
    claimed_by: str
    created_at: float
    updated_at: float
    claimed_at: float | None
    completed_at: float | None
    delivery_directory: str
    last_error: str
    candidate_url: str
    candidate_recorded_at: float | None

    def as_json(self) -> dict[str, object]:
        return asdict(self)


def clean_keyword(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    without_controls = "".join(
        character
        for character in normalized
        if unicodedata.category(character) not in {"Cc", "Cf"}
        or character in {"\t", "\n", "\r"}
    )
    return re.sub(r"\s+", " ", without_controls).strip()


def clean_candidate_url(value: str) -> str:
    candidate = value.strip()
    if not candidate:
        return ""
    if len(candidate) > 2000:
        raise ValueError("candidate URL cannot exceed 2000 characters")
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("candidate URL must be an HTTP or HTTPS URL")
    return candidate


def candidate_rejection_is_terminal(reason: str) -> bool:
    """Return True only for evidence that makes an exact page unusable."""
    normalized = clean_keyword(reason).casefold()
    terminal_markers = (
        "404",
        "410",
        "package_mismatch",
        "package mismatch",
        "包名不匹配",
        "no_download_link",
        "no download link",
        "不再提供",
        "资源已删除",
        "页面已删除",
        "只提供安装器",
        "签名链接无法刷新",
    )
    return any(marker in normalized for marker in terminal_markers)


def keyword_search_filters(query: str) -> tuple[list[str], list[str]]:
    conditions: list[str] = []
    parameters: list[str] = []
    for token in normalize_search_text(query).split():
        escaped = (
            token.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        conditions.append("normalized_keyword LIKE ? ESCAPE '\\'")
        parameters.append(f"%{escaped}%")
    return conditions, parameters


class KeywordQueue:
    """SQLite-backed queue shared by the LAN service and the APK agent."""

    def __init__(
        self,
        database_path: Path,
        *,
        stale_after_seconds: int = 12 * 60 * 60,
    ) -> None:
        self.database_path = database_path.resolve(strict=False)
        self.stale_after_seconds = max(60, stale_after_seconds)

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS keyword_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    keyword TEXT NOT NULL,
                    normalized_keyword TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    search_miss_count INTEGER NOT NULL DEFAULT 0,
                    claimed_by TEXT,
                    claimed_at REAL,
                    completed_at REAL,
                    delivery_directory TEXT,
                    last_error TEXT,
                    candidate_url TEXT,
                    candidate_recorded_at REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    CHECK (
                        status IN (
                            'pending',
                            'processing',
                            'completed',
                            'retry',
                            'paid_skipped',
                            'not_found_skipped',
                            'manual_ios',
                            'manual_paid',
                            'manual_not_found'
                        )
                    )
                );
                CREATE UNIQUE INDEX IF NOT EXISTS keyword_jobs_active_keyword
                    ON keyword_jobs(normalized_keyword)
                    WHERE status IN ('pending', 'processing', 'retry');
                CREATE INDEX IF NOT EXISTS keyword_jobs_status_created
                    ON keyword_jobs(status, created_at, id);
                """
            )
            self._recover_interrupted_migration(connection)
            table_sql_row = connection.execute(
                """
                SELECT sql
                FROM sqlite_master
                WHERE type = 'table' AND name = 'keyword_jobs'
                """
            ).fetchone()
            table_sql = table_sql_row["sql"] if table_sql_row else ""
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(keyword_jobs)"
                ).fetchall()
            }
            if (
                "search_miss_count" not in columns
                or "not_found_skipped" not in table_sql
                or "manual_ios" not in table_sql
                or "manual_paid" not in table_sql
                or "manual_not_found" not in table_sql
                or "candidate_url" not in columns
                or "candidate_recorded_at" not in columns
            ):
                self._migrate_queue_schema(connection, columns)

    @staticmethod
    def _recover_interrupted_migration(
        connection: sqlite3.Connection,
    ) -> None:
        legacy = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'keyword_jobs_legacy'
            """
        ).fetchone()
        if legacy is None:
            return

        current_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM keyword_jobs"
            ).fetchone()[0]
        )
        legacy_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM keyword_jobs_legacy"
            ).fetchone()[0]
        )
        if current_count and legacy_count:
            raise RuntimeError(
                "interrupted queue migration requires manual reconciliation"
            )
        if not legacy_count:
            connection.execute("DROP TABLE keyword_jobs_legacy")
            return

        legacy_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(keyword_jobs_legacy)"
            ).fetchall()
        }
        search_miss_expression = (
            "search_miss_count"
            if "search_miss_count" in legacy_columns
            else "0"
        )
        candidate_url_expression = (
            "candidate_url"
            if "candidate_url" in legacy_columns
            else "NULL"
        )
        candidate_recorded_at_expression = (
            "candidate_recorded_at"
            if "candidate_recorded_at" in legacy_columns
            else "NULL"
        )
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            f"""
            INSERT INTO keyword_jobs (
                id,
                keyword,
                normalized_keyword,
                status,
                attempt_count,
                search_miss_count,
                claimed_by,
                claimed_at,
                completed_at,
                delivery_directory,
                last_error,
                candidate_url,
                candidate_recorded_at,
                created_at,
                updated_at
            )
            SELECT
                id,
                keyword,
                normalized_keyword,
                CASE
                    WHEN status = 'manual_not_found'
                         AND (
                            lower(COALESCE(last_error, '')) LIKE '%ios%'
                            OR COALESCE(last_error, '') LIKE '%苹果%'
                            OR lower(COALESCE(last_error, '')) LIKE '%app store%'
                         )
                        THEN 'manual_ios'
                    WHEN status = 'manual_not_found'
                         AND (
                            COALESCE(last_error, '') LIKE '%付费%'
                            OR COALESCE(last_error, '') LIKE '%购买%'
                            OR COALESCE(last_error, '') LIKE '%价格%'
                            OR lower(COALESCE(last_error, '')) LIKE '%paid%'
                         )
                        THEN 'manual_paid'
                    ELSE status
                END,
                attempt_count,
                {search_miss_expression},
                claimed_by,
                claimed_at,
                completed_at,
                delivery_directory,
                last_error,
                {candidate_url_expression},
                {candidate_recorded_at_expression},
                created_at,
                updated_at
            FROM keyword_jobs_legacy
            """
        )
        recovered_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM keyword_jobs"
            ).fetchone()[0]
        )
        if recovered_count != legacy_count:
            raise RuntimeError("queue migration recovery count mismatch")
        connection.execute("DROP TABLE keyword_jobs_legacy")

    @staticmethod
    def _migrate_queue_schema(
        connection: sqlite3.Connection,
        existing_columns: set[str],
    ) -> None:
        search_miss_expression = (
            "search_miss_count"
            if "search_miss_count" in existing_columns
            else "0"
        )
        candidate_url_expression = (
            "candidate_url"
            if "candidate_url" in existing_columns
            else "NULL"
        )
        candidate_recorded_at_expression = (
            "candidate_recorded_at"
            if "candidate_recorded_at" in existing_columns
            else "NULL"
        )
        connection.executescript(
            f"""
            BEGIN IMMEDIATE;
            DROP INDEX IF EXISTS keyword_jobs_active_keyword;
            DROP INDEX IF EXISTS keyword_jobs_status_created;
            ALTER TABLE keyword_jobs RENAME TO keyword_jobs_legacy;
            CREATE TABLE keyword_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT NOT NULL,
                normalized_keyword TEXT NOT NULL,
                status TEXT NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                search_miss_count INTEGER NOT NULL DEFAULT 0,
                claimed_by TEXT,
                claimed_at REAL,
                completed_at REAL,
                delivery_directory TEXT,
                last_error TEXT,
                candidate_url TEXT,
                candidate_recorded_at REAL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                CHECK (
                    status IN (
                        'pending',
                        'processing',
                        'completed',
                        'retry',
                        'paid_skipped',
                        'not_found_skipped',
                        'manual_ios',
                        'manual_paid',
                        'manual_not_found'
                    )
                )
            );
            INSERT INTO keyword_jobs (
                id,
                keyword,
                normalized_keyword,
                status,
                attempt_count,
                search_miss_count,
                claimed_by,
                claimed_at,
                completed_at,
                delivery_directory,
                last_error,
                candidate_url,
                candidate_recorded_at,
                created_at,
                updated_at
            )
            SELECT
                id,
                keyword,
                normalized_keyword,
                CASE
                    WHEN status = 'manual_not_found'
                         AND (
                            lower(COALESCE(last_error, '')) LIKE '%ios%'
                            OR COALESCE(last_error, '') LIKE '%苹果%'
                            OR lower(COALESCE(last_error, '')) LIKE '%app store%'
                         )
                        THEN 'manual_ios'
                    WHEN status = 'manual_not_found'
                         AND (
                            COALESCE(last_error, '') LIKE '%付费%'
                            OR COALESCE(last_error, '') LIKE '%购买%'
                            OR COALESCE(last_error, '') LIKE '%价格%'
                            OR lower(COALESCE(last_error, '')) LIKE '%paid%'
                         )
                        THEN 'manual_paid'
                    ELSE status
                END,
                attempt_count,
                {search_miss_expression},
                claimed_by,
                claimed_at,
                completed_at,
                delivery_directory,
                last_error,
                {candidate_url_expression},
                {candidate_recorded_at_expression},
                created_at,
                updated_at
            FROM keyword_jobs_legacy;
            DROP TABLE keyword_jobs_legacy;
            CREATE UNIQUE INDEX keyword_jobs_active_keyword
                ON keyword_jobs(normalized_keyword)
                WHERE status IN ('pending', 'processing', 'retry');
            CREATE INDEX keyword_jobs_status_created
                ON keyword_jobs(status, created_at, id);
            COMMIT;
            """
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=30,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _job(row: sqlite3.Row) -> KeywordJob:
        return KeywordJob(
            id=row["id"],
            keyword=row["keyword"],
            status=row["status"],
            attempt_count=row["attempt_count"],
            search_miss_count=row["search_miss_count"],
            claimed_by=row["claimed_by"] or "",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            claimed_at=row["claimed_at"],
            completed_at=row["completed_at"],
            delivery_directory=row["delivery_directory"] or "",
            last_error=row["last_error"] or "",
            candidate_url=row["candidate_url"] or "",
            candidate_recorded_at=row["candidate_recorded_at"],
        )

    def add(self, keywords: list[str]) -> dict[str, list[dict[str, object]]]:
        prepared: list[tuple[str, str]] = []
        seen: set[str] = set()
        invalid: list[dict[str, object]] = []

        for original in keywords:
            keyword = clean_keyword(original)
            normalized = normalize_search_text(keyword)
            if not keyword or not normalized:
                invalid.append({"keyword": original, "reason": "关键词不能为空"})
                continue
            if len(keyword) > 200:
                invalid.append(
                    {"keyword": original, "reason": "关键词不能超过 200 个字符"}
                )
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            prepared.append((keyword, normalized))

        created: list[KeywordJob] = []
        existing: list[KeywordJob] = []
        now = time.time()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for keyword, normalized in prepared:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO keyword_jobs (
                        keyword, normalized_keyword, status,
                        created_at, updated_at
                    ) VALUES (?, ?, 'pending', ?, ?)
                    """,
                    (keyword, normalized, now, now),
                )
                if cursor.rowcount:
                    row = connection.execute(
                        "SELECT * FROM keyword_jobs WHERE id = last_insert_rowid()"
                    ).fetchone()
                    if row is not None:
                        created.append(self._job(row))
                    continue

                row = connection.execute(
                    """
                    SELECT *
                    FROM keyword_jobs
                    WHERE normalized_keyword = ?
                      AND status IN ('pending', 'processing', 'retry')
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (normalized,),
                ).fetchone()
                if row is not None:
                    existing.append(self._job(row))

        return {
            "created": [job.as_json() for job in created],
            "existing": [job.as_json() for job in existing],
            "invalid": invalid,
        }

    def list_jobs(
        self,
        *,
        status: str | None = None,
        query: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[KeywordJob]:
        if status is not None and status not in QUEUE_STATUSES:
            raise ValueError(f"unsupported status: {status}")

        bounded_limit = max(1, min(limit, 500))
        bounded_offset = max(0, offset)
        conditions: list[str] = []
        parameters: list[object] = []
        if status is not None:
            conditions.append("status = ?")
            parameters.append(status)
        search_conditions, search_parameters = keyword_search_filters(query)
        conditions.extend(search_conditions)
        parameters.extend(search_parameters)
        sql = "SELECT * FROM keyword_jobs"
        if conditions:
            sql += f" WHERE {' AND '.join(conditions)}"
        sql += " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
        parameters.extend((bounded_limit, bounded_offset))

        with self._connection() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return [self._job(row) for row in rows]

    def list_jobs_for_statuses(
        self,
        statuses: tuple[str, ...],
        *,
        query: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[KeywordJob]:
        if not statuses or any(status not in QUEUE_STATUSES for status in statuses):
            raise ValueError("unsupported statuses")
        bounded_limit = max(1, min(limit, 500))
        bounded_offset = max(0, offset)
        placeholders = ", ".join("?" for _ in statuses)
        search_conditions, search_parameters = keyword_search_filters(query)
        search_sql = "".join(
            f" AND {condition}" for condition in search_conditions
        )
        sql = f"""
            SELECT *
            FROM keyword_jobs
            WHERE status IN ({placeholders})
              {search_sql}
            ORDER BY COALESCE(completed_at, updated_at) DESC, id DESC
            LIMIT ? OFFSET ?
        """
        parameters: list[object] = [
            *statuses,
            *search_parameters,
            bounded_limit,
            bounded_offset,
        ]
        with self._connection() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return [self._job(row) for row in rows]

    def count_jobs(
        self,
        *,
        status: str | None = None,
        statuses: tuple[str, ...] | None = None,
        query: str = "",
    ) -> int:
        if status is not None and statuses is not None:
            raise ValueError("choose status or statuses, not both")
        if status is not None and status not in QUEUE_STATUSES:
            raise ValueError(f"unsupported status: {status}")
        if statuses is not None and (
            not statuses
            or any(item not in QUEUE_STATUSES for item in statuses)
        ):
            raise ValueError("unsupported statuses")

        conditions: list[str] = []
        parameters: list[object] = []
        if status is not None:
            conditions.append("status = ?")
            parameters.append(status)
        elif statuses is not None:
            placeholders = ", ".join("?" for _ in statuses)
            conditions.append(f"status IN ({placeholders})")
            parameters.extend(statuses)
        search_conditions, search_parameters = keyword_search_filters(query)
        conditions.extend(search_conditions)
        parameters.extend(search_parameters)

        sql = "SELECT COUNT(*) FROM keyword_jobs"
        if conditions:
            sql += f" WHERE {' AND '.join(conditions)}"
        with self._connection() as connection:
            return int(connection.execute(sql, parameters).fetchone()[0])

    def get(self, job_id: int) -> KeywordJob | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM keyword_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        return self._job(row) if row is not None else None

    def remove_pending(self, job_ids: list[int]) -> list[KeywordJob]:
        """Atomically remove jobs that have never started processing."""
        unique_ids = list(dict.fromkeys(job_ids))
        if not unique_ids:
            raise ValueError("at least one job id is required")

        placeholders = ", ".join("?" for _ in unique_ids)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                f"""
                SELECT *
                FROM keyword_jobs
                WHERE id IN ({placeholders})
                ORDER BY id DESC
                """,
                unique_ids,
            ).fetchall()
            jobs_by_id = {row["id"]: self._job(row) for row in rows}
            missing_ids = [job_id for job_id in unique_ids if job_id not in jobs_by_id]
            if missing_ids:
                raise KeyError(missing_ids[0])

            unsafe = [
                job
                for job in jobs_by_id.values()
                if job.status != "pending" or job.attempt_count != 0
            ]
            if unsafe:
                job = unsafe[0]
                raise ValueError(
                    f"job {job.id} cannot be removed from {job.status} "
                    f"after {job.attempt_count} attempts"
                )

            connection.execute(
                f"DELETE FROM keyword_jobs WHERE id IN ({placeholders})",
                unique_ids,
            )

        return [jobs_by_id[job_id] for job_id in unique_ids]

    def snapshot(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, object]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM keyword_jobs
                GROUP BY status
                """
            ).fetchall()
        counts = {status: 0 for status in QUEUE_STATUSES}
        for row in rows:
            counts[row["status"]] = row["count"]
        counts["runnable"] = sum(counts[status] for status in RUNNABLE_STATUSES)
        counts["total"] = sum(counts[status] for status in QUEUE_STATUSES)
        return {
            "counts": counts,
            "items": [
                job.as_json()
                for job in self.list_jobs(limit=limit, offset=offset)
            ],
        }

    def runnable_count(self) -> int:
        with self._connection() as connection:
            return connection.execute(
                """
                SELECT COUNT(*)
                FROM keyword_jobs
                WHERE status IN ('pending', 'retry')
                """
            ).fetchone()[0]

    def claim(self, *, limit: int = 10, worker: str) -> list[KeywordJob]:
        bounded_limit = max(1, min(limit, 10))
        claimed_by = clean_keyword(worker)[:200] or "find-apk-agent"
        now = time.time()
        stale_before = now - self.stale_after_seconds

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE keyword_jobs
                SET status = 'retry',
                    claimed_by = NULL,
                    claimed_at = NULL,
                    last_error = '上一次处理超时，已自动重新排队',
                    updated_at = ?
                WHERE status = 'processing'
                  AND claimed_at IS NOT NULL
                  AND claimed_at < ?
                """,
                (now, stale_before),
            )

            resumed_rows = connection.execute(
                """
                SELECT *
                FROM keyword_jobs
                WHERE status = 'processing'
                  AND claimed_by = ?
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                (claimed_by, bounded_limit),
            ).fetchall()
            if resumed_rows:
                resumed_ids = [row["id"] for row in resumed_rows]
                placeholders = ", ".join("?" for _ in resumed_ids)
                connection.execute(
                    f"""
                    UPDATE keyword_jobs
                    SET claimed_at = ?,
                        updated_at = ?
                    WHERE id IN ({placeholders})
                    """,
                    (now, now, *resumed_ids),
                )
                refreshed_rows = connection.execute(
                    f"""
                    SELECT *
                    FROM keyword_jobs
                    WHERE id IN ({placeholders})
                    ORDER BY created_at ASC, id ASC
                    """,
                    resumed_ids,
                ).fetchall()
                return [self._job(row) for row in refreshed_rows]

            rows = connection.execute(
                """
                SELECT id
                FROM keyword_jobs
                WHERE status IN ('pending', 'retry')
                ORDER BY
                    CASE
                        WHEN status = 'retry' AND candidate_url IS NULL THEN 0
                        WHEN status = 'pending' THEN 1
                        ELSE 2
                    END,
                    created_at ASC,
                    id ASC
                LIMIT ?
                """,
                (bounded_limit,),
            ).fetchall()
            ids = [row["id"] for row in rows]
            if not ids:
                return []

            placeholders = ", ".join("?" for _ in ids)
            connection.execute(
                f"""
                UPDATE keyword_jobs
                SET status = 'processing',
                    attempt_count = attempt_count + 1,
                    claimed_by = ?,
                    claimed_at = ?,
                    completed_at = NULL,
                    last_error = NULL,
                    updated_at = ?
                WHERE id IN ({placeholders})
                """,
                (claimed_by, now, now, *ids),
            )
            claimed_rows = connection.execute(
                f"""
                SELECT *
                FROM keyword_jobs
                WHERE id IN ({placeholders})
                ORDER BY created_at ASC, id ASC
                """,
                ids,
            ).fetchall()
        return [self._job(row) for row in claimed_rows]

    def claim_specific(self, job_id: int, *, worker: str) -> KeywordJob:
        claimed_by = clean_keyword(worker)[:200] or "find-apk-agent"
        now = time.time()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM keyword_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise KeyError(job_id)
            if row["status"] == "processing":
                if row["claimed_by"] != claimed_by:
                    raise ValueError(
                        f"job {job_id} is already claimed by "
                        f"{row['claimed_by']}"
                    )
                connection.execute(
                    """
                    UPDATE keyword_jobs
                    SET claimed_at = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (now, now, job_id),
                )
            elif row["status"] in RUNNABLE_STATUSES:
                connection.execute(
                    """
                    UPDATE keyword_jobs
                    SET status = 'processing',
                        attempt_count = attempt_count + 1,
                        claimed_by = ?,
                        claimed_at = ?,
                        completed_at = NULL,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (claimed_by, now, now, job_id),
                )
            else:
                raise ValueError(
                    f"job {job_id} cannot be claimed from {row['status']}"
                )
            updated = connection.execute(
                "SELECT * FROM keyword_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        assert updated is not None
        return self._job(updated)

    def update(
        self,
        job_id: int,
        *,
        status: str,
        delivery_directory: str = "",
        error: str = "",
    ) -> KeywordJob:
        if status not in {
            "completed",
            "retry",
            "paid_skipped",
            "not_found_skipped",
        }:
            raise ValueError(f"unsupported update status: {status}")

        now = time.time()
        completed_at = (
            now
            if status
            in {"completed", "paid_skipped", "not_found_skipped"}
            else None
        )
        clean_error = clean_keyword(error)[:500]
        clean_directory = delivery_directory.strip()[:1000]

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM keyword_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise KeyError(job_id)
            if row["status"] not in ACTIVE_STATUSES:
                raise ValueError(
                    f"job {job_id} is already {row['status']}"
                )
            claimed_by = None if status == "retry" else row["claimed_by"]
            claimed_at = None if status == "retry" else row["claimed_at"]
            candidate_url = (
                row["candidate_url"]
                if status == "retry"
                else None
            )
            candidate_recorded_at = (
                row["candidate_recorded_at"]
                if status == "retry"
                else None
            )

            connection.execute(
                """
                UPDATE keyword_jobs
                SET status = ?,
                    claimed_by = ?,
                    claimed_at = ?,
                    completed_at = ?,
                    delivery_directory = ?,
                    last_error = ?,
                    candidate_url = ?,
                    candidate_recorded_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    claimed_by,
                    claimed_at,
                    completed_at,
                    clean_directory or None,
                    clean_error or None,
                    candidate_url,
                    candidate_recorded_at,
                    now,
                    job_id,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM keyword_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        assert updated is not None
        return self._job(updated)

    def confirm_not_found(
        self,
        job_id: int,
        *,
        reason: str,
        category: str = "not_found",
    ) -> KeywordJob:
        clean_reason = clean_keyword(reason)[:500]
        if not clean_reason:
            raise ValueError("manual confirmation reason is required")
        manual_status = MANUAL_CATEGORY_STATUSES.get(category)
        if manual_status is None:
            raise ValueError("unsupported manual confirmation category")

        now = time.time()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM keyword_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise KeyError(job_id)
            if row["status"] not in {
                "paid_skipped",
                "not_found_skipped",
                *MANUAL_STATUSES,
            }:
                raise ValueError(
                    f"job {job_id} cannot be manually confirmed from "
                    f"{row['status']}"
                )

            confirmed_at = (
                row["completed_at"]
                if row["status"] in MANUAL_STATUSES
                else now
            )
            connection.execute(
                """
                UPDATE keyword_jobs
                SET status = ?,
                    completed_at = ?,
                    last_error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (manual_status, confirmed_at, clean_reason, now, job_id),
            )
            updated = connection.execute(
                "SELECT * FROM keyword_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        assert updated is not None
        return self._job(updated)

    def update_skipped_reason(self, job_id: int, *, reason: str) -> KeywordJob:
        clean_reason = clean_keyword(reason)[:500]
        if not clean_reason:
            raise ValueError("skipped reason is required")

        now = time.time()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM keyword_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise KeyError(job_id)
            if row["status"] not in {
                "completed",
                "paid_skipped",
                "not_found_skipped",
                *MANUAL_STATUSES,
            }:
                raise ValueError(
                    f"job {job_id} is not an editable skipped record"
                )
            connection.execute(
                """
                UPDATE keyword_jobs
                SET last_error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (clean_reason, now, job_id),
            )
            updated = connection.execute(
                "SELECT * FROM keyword_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        assert updated is not None
        return self._job(updated)

    def record_candidate(self, job_id: int, *, url: str) -> KeywordJob:
        candidate_url = clean_candidate_url(url)
        if not candidate_url:
            raise ValueError("candidate URL is required")
        now = time.time()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM keyword_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise KeyError(job_id)
            if row["status"] not in ACTIVE_STATUSES:
                raise ValueError(
                    f"job {job_id} is already {row['status']}"
                )
            connection.execute(
                """
                UPDATE keyword_jobs
                SET candidate_url = ?,
                    candidate_recorded_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (candidate_url, now, now, job_id),
            )
            updated = connection.execute(
                "SELECT * FROM keyword_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        assert updated is not None
        return self._job(updated)

    def clear_candidate(
        self,
        job_id: int,
        *,
        reason: str,
    ) -> KeywordJob:
        clean_reason = clean_keyword(reason)[:500]
        if not clean_reason:
            raise ValueError("candidate rejection reason is required")
        now = time.time()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM keyword_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise KeyError(job_id)
            if row["status"] != "processing":
                raise ValueError(
                    f"job {job_id} is already {row['status']}"
                )
            if not row["candidate_url"]:
                raise ValueError(f"job {job_id} has no recorded candidate")
            if not candidate_rejection_is_terminal(clean_reason):
                connection.execute(
                    """
                    UPDATE keyword_jobs
                    SET status = 'retry',
                        claimed_by = NULL,
                        claimed_at = NULL,
                        completed_at = NULL,
                        last_error = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        "精确候选仍存在，当前仅因验证或临时下载失败等待重试："
                        f"{clean_reason}",
                        now,
                        job_id,
                    ),
                )
                updated = connection.execute(
                    "SELECT * FROM keyword_jobs WHERE id = ?",
                    (job_id,),
                ).fetchone()
                assert updated is not None
                return self._job(updated)
            connection.execute(
                """
                UPDATE keyword_jobs
                SET candidate_url = NULL,
                    candidate_recorded_at = NULL,
                    last_error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (clean_reason, now, job_id),
            )
            updated = connection.execute(
                "SELECT * FROM keyword_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        assert updated is not None
        return self._job(updated)

    def reopen(
        self,
        job_id: int,
        *,
        reason: str = "",
        candidate_url: str = "",
    ) -> KeywordJob:
        clean_reason = clean_keyword(reason)[:500]
        clean_url = clean_candidate_url(candidate_url)
        now = time.time()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM keyword_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise KeyError(job_id)
            if row["status"] not in {
                "completed",
                "paid_skipped",
                "not_found_skipped",
                *MANUAL_STATUSES,
            }:
                raise ValueError(
                    f"job {job_id} cannot be reopened from {row['status']}"
                )
            duplicate = connection.execute(
                """
                SELECT id
                FROM keyword_jobs
                WHERE normalized_keyword = ?
                  AND status IN ('pending', 'processing', 'retry')
                  AND id != ?
                LIMIT 1
                """,
                (row["normalized_keyword"], job_id),
            ).fetchone()
            if duplicate is not None:
                raise ValueError(
                    f"keyword already active as job {duplicate['id']}"
                )
            connection.execute(
                """
                UPDATE keyword_jobs
                SET status = 'retry',
                    search_miss_count = 0,
                    claimed_by = NULL,
                    claimed_at = NULL,
                    completed_at = NULL,
                    delivery_directory = NULL,
                    last_error = ?,
                    candidate_url = ?,
                    candidate_recorded_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    clean_reason or "人工退回重新查找",
                    clean_url or None,
                    now if clean_url else None,
                    now,
                    job_id,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM keyword_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        assert updated is not None
        return self._job(updated)

    def record_search_miss(
        self,
        job_id: int,
        *,
        reason: str,
        limit: int = SEARCH_MISS_LIMIT,
    ) -> KeywordJob:
        bounded_limit = max(1, limit)
        clean_reason = clean_keyword(reason)[:500]
        if not clean_reason:
            raise ValueError("search miss reason is required")

        now = time.time()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM keyword_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise KeyError(job_id)
            if row["status"] != "processing":
                raise ValueError(
                    f"job {job_id} is already {row['status']}"
                )
            if row["candidate_url"]:
                raise ValueError(
                    "unresolved exact candidate blocks search miss: "
                    f"{row['candidate_url']}"
                )

            search_miss_count = row["search_miss_count"] + 1
            skipped = search_miss_count >= bounded_limit
            status = "not_found_skipped" if skipped else "processing"
            completed_at = now if skipped else None
            connection.execute(
                """
                UPDATE keyword_jobs
                SET status = ?,
                    search_miss_count = ?,
                    completed_at = ?,
                    last_error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    search_miss_count,
                    completed_at,
                    clean_reason,
                    now,
                    job_id,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM keyword_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        assert updated is not None
        return self._job(updated)

    def release_worker(self, worker: str, *, reason: str) -> int:
        claimed_by = clean_keyword(worker)[:200]
        if not claimed_by:
            return 0
        now = time.time()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE keyword_jobs
                SET status = 'retry',
                    claimed_by = NULL,
                    claimed_at = NULL,
                    completed_at = NULL,
                    last_error = ?,
                    updated_at = ?
                WHERE status = 'processing'
                  AND claimed_by = ?
                """,
                (clean_keyword(reason)[:500], now, claimed_by),
            )
        return cursor.rowcount
