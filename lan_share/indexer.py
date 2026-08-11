from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import threading
import time
import unicodedata

from lan_share.bundles import DeliveryFiles
from lan_share.package_identity import identify_package


PACKAGE_SUFFIXES = {".apk", ".xapk", ".apkm", ".apks"}
DATE_DIRECTORY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INDEX_FORMAT_VERSION = "2"


@dataclass(frozen=True)
class Delivery:
    id: int
    keyword: str
    directory_name: str
    developer: str
    package_name: str
    package_format: str
    package_size: int
    date: str
    icon_url: str
    download_url: str


def normalize_search_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(
        character
        for character in normalized
        if unicodedata.category(character) != "Mn"
    )
    return " ".join(
        piece for piece in re.split(r"[^\w]+", without_marks) if piece
    )


def display_name(directory_name: str, developer: str = "") -> str:
    words = re.sub(r"[_-]+", " ", directory_name).strip()
    if not words:
        return directory_name
    fallback = " ".join(
        word if word.isupper() else word.capitalize() for word in words.split()
    )
    directory_key = normalize_search_text(directory_name).replace(" ", "")
    developer_words = re.findall(r"[\w'’.-]+", developer, flags=re.UNICODE)
    for length in range(1, len(developer_words) + 1):
        candidate = " ".join(developer_words[:length]).strip(" .'’-")
        if normalize_search_text(candidate).replace(" ", "") == directory_key:
            return candidate
    return fallback


def format_size(size: int) -> str:
    value = float(size)
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


class DeliveryIndex:
    """Persistent, incremental index of validated Find-APK delivery folders."""

    def __init__(
        self,
        downloads_root: Path,
        database_path: Path,
        validator_path: Path,
        *,
        validation_timeout: int = 180,
    ) -> None:
        self.downloads_root = downloads_root.resolve(strict=False)
        self.database_path = database_path.resolve(strict=False)
        self.validator_path = validator_path.resolve(strict=False)
        self.validation_timeout = validation_timeout
        self._scan_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._is_scanning = False
        self._scan_started_at: float | None = None
        self._last_scan_at: float | None = None
        self._last_error: str | None = None
        self._checked = 0
        self._total = 0

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS deliveries (
                    directory TEXT PRIMARY KEY,
                    signature TEXT NOT NULL,
                    valid INTEGER NOT NULL DEFAULT 0,
                    keyword TEXT,
                    directory_name TEXT,
                    developer TEXT,
                    package_name TEXT,
                    application_id TEXT,
                    identity_checked INTEGER NOT NULL DEFAULT 0,
                    package_relpath TEXT,
                    icon_relpath TEXT,
                    package_format TEXT,
                    package_size INTEGER,
                    delivery_date TEXT,
                    search_text TEXT,
                    checked_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS deliveries_valid_date
                    ON deliveries(valid, delivery_date DESC);
                """
            )
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(deliveries)"
                ).fetchall()
            }
            if "application_id" not in columns:
                connection.execute(
                    "ALTER TABLE deliveries ADD COLUMN application_id TEXT"
                )
            if "identity_checked" not in columns:
                connection.execute(
                    """
                    ALTER TABLE deliveries
                    ADD COLUMN identity_checked INTEGER NOT NULL DEFAULT 0
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

    def status(self) -> dict[str, object]:
        with self._state_lock:
            scanning = self._is_scanning
            started_at = self._scan_started_at
            last_scan_at = self._last_scan_at
            last_error = self._last_error
            checked = self._checked
            total = self._total

        with self._connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM deliveries WHERE valid = 1"
            ).fetchone()[0]

        return {
            "count": count,
            "scanning": scanning,
            "checked": checked,
            "total": total,
            "scan_started_at": started_at,
            "last_scan_at": last_scan_at,
            "last_error": last_error,
        }

    def scan(self) -> bool:
        if not self._scan_lock.acquire(blocking=False):
            return False

        started = time.time()
        with self._state_lock:
            self._is_scanning = True
            self._scan_started_at = started
            self._last_error = None
            self._checked = 0

        try:
            candidates = self._candidate_directories()
            with self._state_lock:
                self._total = len(candidates)

            seen: set[str] = set()
            for position, directory in enumerate(candidates, start=1):
                relative_directory = directory.relative_to(
                    self.downloads_root
                ).as_posix()
                seen.add(relative_directory)
                self._refresh_directory(directory, relative_directory)
                with self._state_lock:
                    self._checked = position

            self._remove_missing(seen)
            with self._state_lock:
                self._last_scan_at = time.time()
            return True
        except Exception as error:
            with self._state_lock:
                self._last_error = f"{type(error).__name__}: {error}"
            return False
        finally:
            with self._state_lock:
                self._is_scanning = False
            self._scan_lock.release()

    def _candidate_directories(self) -> list[Path]:
        if not self.downloads_root.is_dir():
            return []

        candidates: list[Path] = []
        for group in sorted(self.downloads_root.iterdir()):
            if not group.is_dir() or group.is_symlink():
                continue
            # Current queue workers write directly under downloads/, while older
            # batches are grouped by date. Both are valid delivery layouts.
            if self._has_delivery_files(group):
                candidates.append(group)
                continue
            for directory in sorted(group.iterdir()):
                if not directory.is_dir() or directory.is_symlink():
                    continue
                if self._has_delivery_files(directory):
                    candidates.append(directory)
        return candidates

    @staticmethod
    def _has_delivery_files(directory: Path) -> bool:
        try:
            return any(
                child.is_file()
                and (
                    child.name == "developer.txt"
                    or child.name == "source.txt"
                    or child.suffix.casefold() == ".webp"
                    or child.suffix.casefold() in PACKAGE_SUFFIXES
                )
                for child in directory.iterdir()
                if not child.name.startswith(".")
            )
        except OSError:
            return False

    @staticmethod
    def _signature(directory: Path) -> str:
        records: list[tuple[str, int, int]] = []
        for child in sorted(directory.iterdir(), key=lambda path: path.name):
            if (
                not child.is_file()
                or child.name.startswith(".")
                or (
                    child.name != "developer.txt"
                    and child.name != "source.txt"
                    and child.suffix.casefold() != ".webp"
                    and child.suffix.casefold() not in PACKAGE_SUFFIXES
                )
            ):
                continue
            stat = child.stat()
            records.append((child.name, stat.st_size, stat.st_mtime_ns))
        payload = json.dumps(
            (INDEX_FORMAT_VERSION, records),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _refresh_directory(self, directory: Path, relative_directory: str) -> None:
        try:
            signature = self._signature(directory)
        except OSError:
            return

        with self._connection() as connection:
            existing = connection.execute(
                """
                SELECT signature, valid, identity_checked,
                       package_relpath, icon_relpath
                FROM deliveries
                WHERE directory = ?
                """,
                (relative_directory,),
            ).fetchone()
            if (
                existing is not None
                and existing["signature"] == signature
                and existing["identity_checked"]
                and self._stored_delivery_files_exist(existing, directory)
            ):
                return

        validation = self._validate(directory)
        if validation is None:
            self._store_invalid(relative_directory, signature)
            return

        package_path, icon_path, developer_path = validation
        try:
            developer = developer_path.read_text(encoding="utf-8").strip()
            package_stat = package_path.stat()
        except (OSError, UnicodeError):
            self._store_invalid(relative_directory, signature)
            return

        directory_name = directory.name
        keyword = display_name(directory_name, developer)
        parent_name = directory.parent.name
        delivery_date = (
            parent_name
            if DATE_DIRECTORY.fullmatch(parent_name)
            else datetime.fromtimestamp(package_stat.st_mtime).date().isoformat()
        )
        package_relpath = package_path.relative_to(self.downloads_root).as_posix()
        application_id = identify_package(package_path)
        icon_relpath = icon_path.relative_to(self.downloads_root).as_posix()
        package_format = package_path.suffix.removeprefix(".").upper()
        search_text = normalize_search_text(
            " ".join(
                (
                    keyword,
                    directory_name,
                    developer,
                    package_path.name,
                    package_path.stem,
                    package_format,
                )
            )
        )

        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO deliveries (
                    directory, signature, valid, keyword, directory_name,
                    developer, package_name, application_id, identity_checked,
                    package_relpath, icon_relpath, package_format, package_size,
                    delivery_date, search_text, checked_at
                ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(directory) DO UPDATE SET
                    signature = excluded.signature,
                    valid = 1,
                    keyword = excluded.keyword,
                    directory_name = excluded.directory_name,
                    developer = excluded.developer,
                    package_name = excluded.package_name,
                    application_id = excluded.application_id,
                    identity_checked = 1,
                    package_relpath = excluded.package_relpath,
                    icon_relpath = excluded.icon_relpath,
                    package_format = excluded.package_format,
                    package_size = excluded.package_size,
                    delivery_date = excluded.delivery_date,
                    search_text = excluded.search_text,
                    checked_at = excluded.checked_at
                """,
                (
                    relative_directory,
                    signature,
                    keyword,
                    directory_name,
                    developer,
                    package_path.name,
                    application_id,
                    package_relpath,
                    icon_relpath,
                    package_format,
                    package_stat.st_size,
                    delivery_date,
                    search_text,
                    time.time(),
                ),
            )

    def _stored_delivery_files_exist(
        self,
        existing: sqlite3.Row,
        directory: Path,
    ) -> bool:
        if not existing["valid"]:
            return True
        relative_paths = (
            existing["package_relpath"],
            existing["icon_relpath"],
        )
        if not all(relative_paths):
            return False
        stored_files = tuple(
            (self.downloads_root / relative_path).resolve(strict=False)
            for relative_path in relative_paths
        )
        return (
            (directory / "developer.txt").is_file()
            and all(path.is_file() for path in stored_files)
            and all(self._is_within_downloads(path) for path in stored_files)
        )

    def _store_invalid(self, relative_directory: str, signature: str) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO deliveries (
                    directory, signature, valid, checked_at
                ) VALUES (?, ?, 0, ?)
                ON CONFLICT(directory) DO UPDATE SET
                    signature = excluded.signature,
                    valid = 0,
                    keyword = NULL,
                    directory_name = NULL,
                    developer = NULL,
                    package_name = NULL,
                    application_id = NULL,
                    identity_checked = 1,
                    package_relpath = NULL,
                    icon_relpath = NULL,
                    package_format = NULL,
                    package_size = NULL,
                    delivery_date = NULL,
                    search_text = NULL,
                    checked_at = excluded.checked_at
                """,
                (relative_directory, signature, time.time()),
            )

    def _validate(self, directory: Path) -> tuple[Path, Path, Path] | None:
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(self.validator_path),
                    str(directory),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.validation_timeout,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None

        if completed.returncode != 0:
            return None

        values: dict[str, str] = {}
        for line in completed.stdout.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                values[key] = value
        if values.get("classification") != "valid_delivery":
            return None

        try:
            package = Path(values["package"]).resolve(strict=True)
            icon = Path(values["icon"]).resolve(strict=True)
            developer = Path(values["developer"]).resolve(strict=True)
        except (KeyError, OSError):
            return None

        if not all(
            self._is_within_downloads(path) for path in (package, icon, developer)
        ):
            return None
        return package, icon, developer

    def _remove_missing(self, seen: set[str]) -> None:
        with self._connection() as connection:
            rows = connection.execute("SELECT directory FROM deliveries").fetchall()
            missing = [
                row["directory"]
                for row in rows
                if row["directory"] not in seen
            ]
            connection.executemany(
                "DELETE FROM deliveries WHERE directory = ?",
                ((directory,) for directory in missing),
            )

    def search(self, query: str = "", *, limit: int = 100) -> list[Delivery]:
        tokens = normalize_search_text(query).split()
        conditions = ["valid = 1"]
        parameters: list[object] = []
        for token in tokens:
            conditions.append(
                "(search_text LIKE ? ESCAPE '\\' "
                "OR REPLACE(search_text, ' ', '') LIKE ? ESCAPE '\\')"
            )
            escaped = token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            parameters.append(f"%{escaped}%")
            parameters.append(f"%{escaped}%")
        parameters.append(max(1, min(limit, 200)))

        sql = f"""
            SELECT rowid, *
            FROM deliveries
            WHERE {' AND '.join(conditions)}
            ORDER BY delivery_date DESC, keyword COLLATE NOCASE ASC
            LIMIT ?
        """
        with self._connection() as connection:
            rows = connection.execute(sql, parameters).fetchall()

        return [
            Delivery(
                id=row["rowid"],
                keyword=row["keyword"],
                directory_name=row["directory_name"],
                developer=row["developer"],
                package_name=row["package_name"],
                package_format=row["package_format"],
                package_size=row["package_size"],
                date=row["delivery_date"],
                icon_url=f"/icon/{row['rowid']}",
                download_url=f"/download/{row['rowid']}",
            )
            for row in rows
        ]

    def search_json(self, query: str = "", *, limit: int = 100) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for delivery in self.search(query, limit=limit):
            item = asdict(delivery)
            item["package_size_label"] = format_size(delivery.package_size)
            items.append(item)
        return items

    def production_candidates(self) -> list[dict[str, object]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT rowid, *
                FROM deliveries
                WHERE valid = 1
                ORDER BY delivery_date ASC, keyword COLLATE NOCASE ASC
                """
            ).fetchall()
        return [
            {
                "id": row["rowid"],
                "delivery_key": f"{row['directory']}:{row['signature']}",
                "directory": row["directory"],
                "signature": row["signature"],
                "keyword": row["keyword"],
                "developer": row["developer"],
                "package_name": row["package_name"],
                "application_id": row["application_id"],
                "package_format": row["package_format"],
                "package_size": row["package_size"],
                "package_size_label": format_size(row["package_size"]),
                "date": row["delivery_date"],
                "icon_url": f"/icon/{row['rowid']}",
                "download_url": f"/download/{row['rowid']}",
            }
            for row in rows
        ]

    def resolve_production_record(
        self,
        delivery_id: int,
    ) -> dict[str, str] | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT directory, signature, keyword
                FROM deliveries
                WHERE rowid = ? AND valid = 1
                """,
                (delivery_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "directory": row["directory"],
            "delivery_key": f"{row['directory']}:{row['signature']}",
            "keyword": row["keyword"],
        }

    def resolve_file(self, delivery_id: int, kind: str) -> Path | None:
        column = {
            "package": "package_relpath",
            "icon": "icon_relpath",
        }.get(kind)
        if column is None:
            return None

        with self._connection() as connection:
            row = connection.execute(
                f"SELECT {column} AS relative_path FROM deliveries "
                "WHERE rowid = ? AND valid = 1",
                (delivery_id,),
            ).fetchone()
        if row is None or not row["relative_path"]:
            return None

        candidate = (self.downloads_root / row["relative_path"]).resolve(strict=False)
        if not candidate.is_file() or not self._is_within_downloads(candidate):
            return None
        return candidate

    def resolve_delivery_files(self, delivery_id: int) -> DeliveryFiles | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT directory, directory_name, package_relpath, icon_relpath
                FROM deliveries
                WHERE rowid = ? AND valid = 1
                """,
                (delivery_id,),
            ).fetchone()
        if row is None:
            return None

        directory = (self.downloads_root / row["directory"]).resolve(
            strict=False
        )
        package = (self.downloads_root / row["package_relpath"]).resolve(
            strict=False
        )
        icon = (self.downloads_root / row["icon_relpath"]).resolve(strict=False)
        developer = (directory / "developer.txt").resolve(strict=False)

        required = (directory, package, icon, developer)
        if (
            not directory.is_dir()
            or not all(path.is_file() for path in required[1:])
            or not all(self._is_within_downloads(path) for path in required)
        ):
            return None

        source_candidate = (directory / "source.txt").resolve(strict=False)
        source = (
            source_candidate
            if source_candidate.is_file()
            and self._is_within_downloads(source_candidate)
            else None
        )
        return DeliveryFiles(
            directory_name=row["directory_name"],
            package=package,
            icon=icon,
            developer=developer,
            source=source,
        )

    def _is_within_downloads(self, path: Path) -> bool:
        try:
            path.relative_to(self.downloads_root)
            return True
        except ValueError:
            return False
