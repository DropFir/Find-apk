from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
import re
import sqlite3
import time
import unicodedata

from lan_share.indexer import format_size


@dataclass(frozen=True)
class ErrorApkReport:
    id: int
    original_name: str
    stored_name: str
    reason: str
    size: int
    created_at: float

    def as_json(self) -> dict[str, object]:
        item = asdict(self)
        item.pop("stored_name", None)
        item["size_label"] = format_size(self.size)
        item["download_url"] = f"/api/error-apks/{self.id}/download"
        return item


def clean_error_filename(value: str) -> str:
    normalized = unicodedata.normalize("NFC", Path(value).name)
    cleaned = "".join(
        character
        for character in normalized
        if unicodedata.category(character) not in {"Cc", "Cf"}
    ).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned or len(cleaned) > 200:
        raise ValueError("ZIP filename is invalid")
    if Path(cleaned).suffix.casefold() != ".zip":
        raise ValueError("only ZIP files are accepted")
    return cleaned


def clean_error_reason(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    cleaned = "".join(
        character
        for character in normalized
        if unicodedata.category(character) not in {"Cc", "Cf"}
        or character in {"\n", "\r", "\t"}
    )
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\r\n?", "\n", cleaned).strip()
    if not cleaned:
        raise ValueError("reason is required")
    if len(cleaned) > 2000:
        raise ValueError("reason cannot exceed 2000 characters")
    return cleaned


class ErrorApkStore:
    def __init__(self, database_path: Path, files_root: Path) -> None:
        self.database_path = database_path.resolve(strict=False)
        self.files_root = files_root.resolve(strict=False)

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.files_root.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS error_apk_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    original_name TEXT NOT NULL,
                    stored_name TEXT NOT NULL UNIQUE,
                    reason TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS error_apk_reports_created
                    ON error_apk_reports(created_at DESC, id DESC);
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
    def _from_row(row: sqlite3.Row) -> ErrorApkReport:
        return ErrorApkReport(
            id=row["id"],
            original_name=row["original_name"],
            stored_name=row["stored_name"],
            reason=row["reason"],
            size=row["size"],
            created_at=row["created_at"],
        )

    def add(
        self,
        *,
        original_name: str,
        stored_name: str,
        reason: str,
        size: int,
    ) -> ErrorApkReport:
        now = time.time()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO error_apk_reports (
                    original_name, stored_name, reason, size, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (original_name, stored_name, reason, size, now),
            )
            row = connection.execute(
                "SELECT * FROM error_apk_reports WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return self._from_row(row)

    def list(self, *, limit: int = 100) -> list[ErrorApkReport]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM error_apk_reports
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def count(self) -> int:
        with self._connection() as connection:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM error_apk_reports"
                ).fetchone()[0]
            )

    def resolve_file(self, report_id: int) -> tuple[Path, str] | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT original_name, stored_name
                FROM error_apk_reports
                WHERE id = ?
                """,
                (report_id,),
            ).fetchone()
        if row is None:
            return None
        path = (self.files_root / row["stored_name"]).resolve(strict=False)
        try:
            path.relative_to(self.files_root)
        except ValueError:
            return None
        if not path.is_file() or path.is_symlink():
            return None
        return path, row["original_name"]
