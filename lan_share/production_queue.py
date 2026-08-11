from __future__ import annotations

from contextlib import contextmanager
from datetime import date, timedelta
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
import unicodedata


LANES = (1, 2)


def normalize_keyword(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(
        character
        for character in normalized
        if unicodedata.category(character) != "Mn"
    )
    return " ".join(
        piece for piece in re.split(r"[^\w]+", without_marks) if piece
    )


class ProductionQueue:
    """Persistent two-lane queue with immutable daily history snapshots."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path.resolve(strict=False)
        self._write_lock = threading.RLock()

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS production_jobs (
                    delivery_key TEXT PRIMARY KEY,
                    directory TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    lane INTEGER NOT NULL CHECK (lane IN (1, 2)),
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'downloaded')),
                    work_date TEXT NOT NULL,
                    assigned_at REAL NOT NULL,
                    downloaded_at REAL
                );
                CREATE INDEX IF NOT EXISTS production_jobs_date_lane
                    ON production_jobs(work_date, lane, assigned_at);
                CREATE TABLE IF NOT EXISTS production_daily_entries (
                    work_date TEXT NOT NULL,
                    delivery_key TEXT NOT NULL,
                    lane INTEGER NOT NULL CHECK (lane IN (1, 2)),
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'downloaded', 'rolled')),
                    assigned_at REAL NOT NULL,
                    downloaded_at REAL,
                    snapshot_json TEXT,
                    PRIMARY KEY (work_date, delivery_key)
                );
                CREATE INDEX IF NOT EXISTS production_daily_date_lane
                    ON production_daily_entries(work_date, lane, assigned_at);
                CREATE TABLE IF NOT EXISTS production_exclusions (
                    delivery_key TEXT PRIMARY KEY,
                    keyword TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    matched_name TEXT,
                    matched_package TEXT,
                    match_type TEXT NOT NULL,
                    excluded_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS production_external_completions (
                    delivery_key TEXT PRIMARY KEY,
                    keyword TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    matched_name TEXT,
                    matched_package TEXT NOT NULL,
                    completed_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS production_removals (
                    delivery_key TEXT PRIMARY KEY,
                    directory TEXT NOT NULL,
                    removed_at REAL NOT NULL
                );
                INSERT OR IGNORE INTO production_daily_entries (
                    work_date, delivery_key, lane, status, assigned_at,
                    downloaded_at
                )
                SELECT work_date, delivery_key, lane, status, assigned_at,
                       downloaded_at
                FROM production_jobs;
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
    def _snapshot(delivery: dict[str, object]) -> str:
        return json.dumps(
            delivery,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @staticmethod
    def _deduplicate_deliveries(
        deliveries: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        """Keep only the newest indexed delivery for each Android package."""
        selected: dict[tuple[str, str], dict[str, object]] = {}
        order: list[tuple[str, str]] = []
        for delivery in deliveries:
            application_id = str(
                delivery.get("application_id") or ""
            ).strip().casefold()
            delivery_key = str(delivery["delivery_key"])
            identity = (
                ("package", application_id)
                if application_id
                else ("delivery", delivery_key)
            )
            existing = selected.get(identity)
            if existing is None:
                selected[identity] = delivery
                order.append(identity)
                continue
            existing_score = (
                str(existing.get("date") or ""),
                int(existing.get("id") or 0),
                str(existing["delivery_key"]),
            )
            delivery_score = (
                str(delivery.get("date") or ""),
                int(delivery.get("id") or 0),
                delivery_key,
            )
            if delivery_score > existing_score:
                selected[identity] = delivery
        return [selected[identity] for identity in order]

    def _prune_missing_active_jobs(
        self,
        connection: sqlite3.Connection,
        candidate_keys: set[str],
        today: str,
    ) -> None:
        rows = connection.execute(
            """
            SELECT delivery_key
            FROM production_jobs
            WHERE status = 'active'
            """
        ).fetchall()
        stale_keys = [
            row["delivery_key"]
            for row in rows
            if row["delivery_key"] not in candidate_keys
        ]
        for key in stale_keys:
            connection.execute(
                """
                UPDATE production_daily_entries
                SET status = 'rolled'
                WHERE delivery_key = ?
                  AND work_date < ?
                  AND status = 'active'
                """,
                (key, today),
            )
            connection.execute(
                """
                DELETE FROM production_daily_entries
                WHERE delivery_key = ?
                  AND work_date >= ?
                  AND status = 'active'
                """,
                (key, today),
            )
            connection.execute(
                """
                DELETE FROM production_jobs
                WHERE delivery_key = ? AND status = 'active'
                """,
                (key,),
            )

    @staticmethod
    def _dates_after(start: str, end: str) -> list[str]:
        current = date.fromisoformat(start) + timedelta(days=1)
        final = date.fromisoformat(end)
        values: list[str] = []
        while current <= final:
            values.append(current.isoformat())
            current += timedelta(days=1)
        return values

    def _roll_active_jobs(
        self,
        connection: sqlite3.Connection,
        candidates: dict[str, dict[str, object]],
        today: str,
    ) -> None:
        rows = connection.execute(
            """
            SELECT delivery_key, lane, status, work_date, assigned_at
            FROM production_jobs
            WHERE status = 'active' AND work_date < ?
            ORDER BY assigned_at, delivery_key
            """,
            (today,),
        ).fetchall()
        for row in rows:
            key = row["delivery_key"]
            delivery = candidates.get(key)
            if delivery is None:
                continue
            previous_date = row["work_date"]
            snapshot = self._snapshot(delivery)
            for next_date in self._dates_after(previous_date, today):
                connection.execute(
                    """
                    UPDATE production_daily_entries
                    SET status = 'rolled'
                    WHERE work_date = ?
                      AND delivery_key = ?
                      AND status = 'active'
                    """,
                    (previous_date, key),
                )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO production_daily_entries (
                        work_date, delivery_key, lane, status, assigned_at,
                        snapshot_json
                    ) VALUES (?, ?, ?, 'active', ?, ?)
                    """,
                    (
                        next_date,
                        key,
                        row["lane"],
                        row["assigned_at"],
                        snapshot,
                    ),
                )
                previous_date = next_date
            connection.execute(
                """
                UPDATE production_jobs
                SET work_date = ?
                WHERE delivery_key = ? AND status = 'active'
                """,
                (today, key),
            )

    def _add_new_jobs(
        self,
        connection: sqlite3.Connection,
        deliveries: list[dict[str, object]],
        known_keys: set[str],
        today: str,
    ) -> None:
        counts = {
            lane: connection.execute(
                """
                SELECT COUNT(*)
                FROM production_daily_entries
                WHERE work_date = ? AND lane = ?
                """,
                (today, lane),
            ).fetchone()[0]
            for lane in LANES
        }
        now = time.time()
        position = 0
        for delivery in deliveries:
            key = str(delivery["delivery_key"])
            if key in known_keys:
                continue
            lane = 1 if counts[1] <= counts[2] else 2
            assigned_at = now + position * 0.000001
            snapshot = self._snapshot(delivery)
            connection.execute(
                """
                INSERT INTO production_jobs (
                    delivery_key, directory, signature, lane, status,
                    work_date, assigned_at
                ) VALUES (?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    key,
                    str(delivery["directory"]),
                    str(delivery["signature"]),
                    lane,
                    today,
                    assigned_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO production_daily_entries (
                    work_date, delivery_key, lane, status, assigned_at,
                    snapshot_json
                ) VALUES (?, ?, ?, 'active', ?, ?)
                """,
                (today, key, lane, assigned_at, snapshot),
            )
            known_keys.add(key)
            counts[lane] += 1
            position += 1

    def _refresh_snapshots(
        self,
        connection: sqlite3.Connection,
        candidates: dict[str, dict[str, object]],
        today: str,
    ) -> None:
        for key, delivery in candidates.items():
            connection.execute(
                """
                UPDATE production_daily_entries
                SET snapshot_json = ?
                WHERE delivery_key = ?
                  AND (work_date = ? OR snapshot_json IS NULL)
                """,
                (self._snapshot(delivery), key, today),
            )

    def _backfill_delivery_history(
        self,
        connection: sqlite3.Connection,
        candidates: dict[str, dict[str, object]],
    ) -> None:
        rows = connection.execute(
            """
            SELECT delivery_key, lane, status, work_date, assigned_at,
                   downloaded_at
            FROM production_jobs
            ORDER BY assigned_at, delivery_key
            """
        ).fetchall()
        for row in rows:
            delivery = candidates.get(row["delivery_key"])
            if delivery is None:
                continue
            try:
                start = date.fromisoformat(str(delivery.get("date", "")))
                end = date.fromisoformat(row["work_date"])
            except ValueError:
                start = date.fromisoformat(row["work_date"])
                end = start
            if start > end:
                start = end
            snapshot = self._snapshot(delivery)
            current = start
            while current <= end:
                entry_date = current.isoformat()
                final_entry = entry_date == row["work_date"]
                entry_status = row["status"] if final_entry else "rolled"
                downloaded_at = row["downloaded_at"] if final_entry else None
                connection.execute(
                    """
                    INSERT OR IGNORE INTO production_daily_entries (
                        work_date, delivery_key, lane, status, assigned_at,
                        downloaded_at, snapshot_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry_date,
                        row["delivery_key"],
                        row["lane"],
                        entry_status,
                        row["assigned_at"],
                        downloaded_at,
                        snapshot,
                    ),
                )
                current += timedelta(days=1)

    def _lane_items(
        self,
        connection: sqlite3.Connection,
        candidates: dict[str, dict[str, object]],
        lane: int,
        selected_date: str,
    ) -> list[dict[str, object]]:
        rows = connection.execute(
            """
            SELECT daily.delivery_key, daily.status, daily.work_date,
                   daily.downloaded_at, daily.snapshot_json,
                   external.completed_at AS external_completed_at,
                   external.matched_name AS external_name,
                   external.matched_package AS external_package
            FROM production_daily_entries AS daily
            LEFT JOIN production_external_completions AS external
              ON external.delivery_key = daily.delivery_key
            WHERE daily.work_date = ? AND daily.lane = ?
              AND NOT EXISTS (
                  SELECT 1
                  FROM production_exclusions AS exclusion
                  WHERE exclusion.delivery_key = daily.delivery_key
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM production_removals AS removal
                  WHERE removal.delivery_key = daily.delivery_key
              )
            ORDER BY daily.assigned_at, daily.delivery_key
            """,
            (selected_date, lane),
        ).fetchall()
        items: list[dict[str, object]] = []
        for row in rows:
            candidate = candidates.get(row["delivery_key"])
            if candidate is None and row["snapshot_json"]:
                try:
                    candidate = json.loads(row["snapshot_json"])
                except (json.JSONDecodeError, TypeError):
                    candidate = None
            if candidate is None:
                continue
            item = dict(candidate)
            item["lane"] = lane
            item["work_date"] = row["work_date"]
            externally_completed = row["external_completed_at"] is not None
            item["queue_status"] = (
                "external_completed"
                if externally_completed and row["status"] == "downloaded"
                else row["status"]
            )
            item["downloaded"] = row["status"] == "downloaded"
            item["downloaded_at"] = row["downloaded_at"]
            item["external_completed"] = externally_completed
            item["external_name"] = row["external_name"]
            item["external_package"] = row["external_package"]
            items.append(item)
        return items

    @staticmethod
    def _count_date(
        connection: sqlite3.Connection,
        selected_date: str,
    ) -> dict[str, object]:
        rows = connection.execute(
            """
            SELECT lane, status, COUNT(*) AS amount
            FROM production_daily_entries
            WHERE work_date = ?
              AND NOT EXISTS (
                  SELECT 1
                  FROM production_exclusions AS exclusion
                  WHERE exclusion.delivery_key =
                        production_daily_entries.delivery_key
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM production_removals AS removal
                  WHERE removal.delivery_key =
                        production_daily_entries.delivery_key
              )
            GROUP BY lane, status
            """,
            (selected_date,),
        ).fetchall()
        lane_counts = {"1": 0, "2": 0}
        downloaded = 0
        for row in rows:
            lane_counts[str(row["lane"])] += row["amount"]
            if row["status"] == "downloaded":
                downloaded += row["amount"]
        return {
            "date": selected_date,
            "counts": lane_counts,
            "total": lane_counts["1"] + lane_counts["2"],
            "downloaded": downloaded,
        }

    def sync_and_list(
        self,
        deliveries: list[dict[str, object]],
        *,
        work_date: str | None = None,
        lane_dates: dict[int, str] | None = None,
    ) -> dict[str, object]:
        today = work_date or date.today().isoformat()
        selected_dates = {
            1: (lane_dates or {}).get(1, today),
            2: (lane_dates or {}).get(2, today),
        }
        with self._write_lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            exclusion_rows = connection.execute(
                "SELECT delivery_key, keyword FROM production_exclusions"
            ).fetchall()
            excluded_keys = {row["delivery_key"] for row in exclusion_rows}
            excluded_keywords = {
                normalize_keyword(row["keyword"])
                for row in exclusion_rows
                if normalize_keyword(row["keyword"])
            }
            removed_keys = {
                row["delivery_key"]
                for row in connection.execute(
                    "SELECT delivery_key FROM production_removals"
                ).fetchall()
            }
            deliveries = [
                delivery
                for delivery in deliveries
                if (
                    str(delivery["delivery_key"]) not in excluded_keys
                    and str(delivery["delivery_key"]) not in removed_keys
                    and normalize_keyword(str(delivery["keyword"]))
                    not in excluded_keywords
                )
            ]
            deliveries = self._deduplicate_deliveries(deliveries)
            candidates = {
                str(delivery["delivery_key"]): delivery
                for delivery in deliveries
            }
            self._prune_missing_active_jobs(
                connection,
                set(candidates),
                today,
            )
            known_keys = {
                row["delivery_key"]
                for row in connection.execute(
                    "SELECT delivery_key FROM production_jobs"
                ).fetchall()
            }
            self._roll_active_jobs(connection, candidates, today)
            self._add_new_jobs(
                connection,
                deliveries,
                known_keys,
                today,
            )
            self._backfill_delivery_history(connection, candidates)
            self._refresh_snapshots(connection, candidates, today)

            lanes = {
                str(lane): self._lane_items(
                    connection,
                    candidates,
                    lane,
                    selected_dates[lane],
                )
                for lane in LANES
            }
            yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
            yesterday_summary = self._count_date(connection, yesterday)
            today_summary = self._count_date(connection, today)
            available = [
                row["work_date"]
                for row in connection.execute(
                    """
                    SELECT DISTINCT work_date
                    FROM production_daily_entries
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM production_exclusions AS exclusion
                        WHERE exclusion.delivery_key =
                              production_daily_entries.delivery_key
                    )
                      AND NOT EXISTS (
                        SELECT 1
                        FROM production_removals AS removal
                        WHERE removal.delivery_key =
                              production_daily_entries.delivery_key
                    )
                    ORDER BY work_date DESC
                    """
                ).fetchall()
            ]

        return {
            "date": today,
            "lane_dates": {
                "1": selected_dates[1],
                "2": selected_dates[2],
            },
            "total": len(lanes["1"]) + len(lanes["2"]),
            "lanes": lanes,
            "counts": {
                "1": len(lanes["1"]),
                "2": len(lanes["2"]),
            },
            "downloaded": sum(
                bool(item["downloaded"])
                for lane in lanes.values()
                for item in lane
            ),
            "today": today_summary,
            "yesterday": yesterday_summary,
            "available_dates": available,
        }

    def downloaded_removal_candidates(self) -> list[dict[str, str]]:
        """List locally downloaded deliveries that are safe to remove."""
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT job.delivery_key, job.directory
                FROM production_jobs AS job
                WHERE job.status = 'downloaded'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM production_external_completions AS external
                      WHERE external.delivery_key = job.delivery_key
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM production_removals AS removal
                      WHERE removal.delivery_key = job.delivery_key
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM production_jobs AS active
                      WHERE active.directory = job.directory
                        AND active.status = 'active'
                  )
                ORDER BY job.downloaded_at, job.delivery_key
                """
            ).fetchall()
        return [
            {
                "delivery_key": row["delivery_key"],
                "directory": row["directory"],
            }
            for row in rows
        ]

    def record_removed_downloads(
        self,
        deliveries: list[dict[str, str]],
    ) -> int:
        """Hide deleted downloaded deliveries while retaining queue history."""
        if not deliveries:
            return 0
        now = time.time()
        created = 0
        with self._write_lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for delivery in deliveries:
                delivery_key = delivery["delivery_key"]
                directory = delivery["directory"]
                row = connection.execute(
                    """
                    SELECT status, directory
                    FROM production_jobs
                    WHERE delivery_key = ?
                    """,
                    (delivery_key,),
                ).fetchone()
                if row is None:
                    raise KeyError(delivery_key)
                if row["status"] != "downloaded" or row["directory"] != directory:
                    raise ValueError(
                        f"delivery {delivery_key} is not a removable download"
                    )
                external = connection.execute(
                    """
                    SELECT 1
                    FROM production_external_completions
                    WHERE delivery_key = ?
                    """,
                    (delivery_key,),
                ).fetchone()
                if external is not None:
                    raise ValueError(
                        f"delivery {delivery_key} was completed externally"
                    )
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO production_removals (
                        delivery_key, directory, removed_at
                    ) VALUES (?, ?, ?)
                    """,
                    (delivery_key, directory, now),
                )
                created += cursor.rowcount
        return created

    def exclude_deliveries(
        self,
        matches: list[dict[str, str]],
        *,
        source_url: str,
    ) -> dict[str, int]:
        now = time.time()
        created = 0
        existing = 0
        with self._write_lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            expanded = list(matches)
            seen_keys = {match["delivery_key"] for match in expanded}
            matches_by_keyword = {
                normalize_keyword(match["keyword"]): match
                for match in matches
                if normalize_keyword(match["keyword"])
            }
            history_rows = connection.execute(
                """
                SELECT DISTINCT delivery_key, snapshot_json
                FROM production_daily_entries
                WHERE snapshot_json IS NOT NULL
                """
            ).fetchall()
            for row in history_rows:
                if row["delivery_key"] in seen_keys:
                    continue
                try:
                    snapshot = json.loads(row["snapshot_json"])
                except (json.JSONDecodeError, TypeError):
                    continue
                keyword = str(snapshot.get("keyword") or "")
                original = matches_by_keyword.get(normalize_keyword(keyword))
                if original is None:
                    continue
                expanded.append(
                    {
                        **original,
                        "delivery_key": row["delivery_key"],
                        "keyword": keyword or original["keyword"],
                    }
                )
                seen_keys.add(row["delivery_key"])

            for match in expanded:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO production_exclusions (
                        delivery_key, keyword, source_url, matched_name,
                        matched_package, match_type, excluded_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        match["delivery_key"],
                        match["keyword"],
                        source_url,
                        match.get("matched_name"),
                        match.get("matched_package"),
                        match["match_type"],
                        now,
                    ),
                )
                if cursor.rowcount == 1:
                    created += 1
                else:
                    existing += 1
        return {
            "created": created,
            "existing": existing,
            "total": created + existing,
        }

    def mark_downloaded(
        self,
        delivery_key: str,
        *,
        work_date: str | None = None,
    ) -> bool:
        today = work_date or date.today().isoformat()
        now = time.time()
        # Queue refresh holds a write transaction while it reconciles the
        # daily snapshot. Serialize the user's download mark with that refresh
        # so SQLite never reaches its busy timeout during a download click.
        with self._write_lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT status, work_date, lane, assigned_at
                FROM production_jobs
                WHERE delivery_key = ?
                """,
                (delivery_key,),
            ).fetchone()
            if row is None:
                return False
            if row["status"] == "downloaded":
                return True
            if row["work_date"] != today:
                return False
            cursor = connection.execute(
                """
                UPDATE production_jobs
                SET status = 'downloaded', downloaded_at = ?
                WHERE delivery_key = ? AND status = 'active'
                """,
                (now, delivery_key),
            )
            connection.execute(
                """
                UPDATE production_daily_entries
                SET status = 'downloaded', downloaded_at = ?
                WHERE delivery_key = ?
                  AND work_date = ?
                  AND status = 'active'
                """,
                (now, delivery_key, today),
            )
        return cursor.rowcount == 1

    def mark_external_completed(
        self,
        delivery_key: str,
        *,
        keyword: str,
        source_url: str,
        matched_name: str,
        matched_package: str,
        work_date: str | None = None,
    ) -> bool:
        today = work_date or date.today().isoformat()
        now = time.time()
        with self._write_lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT 1
                FROM production_external_completions
                WHERE delivery_key = ?
                """,
                (delivery_key,),
            ).fetchone()
            if existing is not None:
                return False
            row = connection.execute(
                """
                SELECT status, work_date
                FROM production_jobs
                WHERE delivery_key = ?
                """,
                (delivery_key,),
            ).fetchone()
            if (
                row is None
                or row["status"] != "active"
                or row["work_date"] != today
            ):
                return False
            connection.execute(
                """
                UPDATE production_jobs
                SET status = 'downloaded', downloaded_at = ?
                WHERE delivery_key = ? AND status = 'active'
                """,
                (now, delivery_key),
            )
            connection.execute(
                """
                UPDATE production_daily_entries
                SET status = 'downloaded', downloaded_at = ?
                WHERE delivery_key = ?
                  AND work_date = ?
                  AND status = 'active'
                """,
                (now, delivery_key, today),
            )
            connection.execute(
                """
                INSERT INTO production_external_completions (
                    delivery_key, keyword, source_url, matched_name,
                    matched_package, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    delivery_key,
                    keyword,
                    source_url,
                    matched_name,
                    matched_package,
                    now,
                ),
            )
        return True
