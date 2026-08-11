from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import os
from pathlib import Path
import shutil
import sqlite3
import threading
import time
from typing import Callable, Iterator
from urllib.parse import urlparse, urlunparse


TASK_STATUSES = (
    "pending",
    "navigating",
    "verifying",
    "downloading",
    "completed",
    "failed",
)
ACTIVE_TASK_STATUSES = ("pending", "navigating", "verifying", "downloading")
CHROME_PATH = Path(
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
)


class BrowserWorkerError(RuntimeError):
    pass


class BrowserWorkerUnavailable(BrowserWorkerError):
    pass


@dataclass(frozen=True)
class BrowserDownloadTask:
    id: int
    entry_page_url: str
    page_url: str
    download_url: str
    suffix: str
    status: str
    detail: str
    progress: float
    received_bytes: int
    total_bytes: int
    result_path: str
    final_url: str
    error: str
    created_at: float
    updated_at: float
    started_at: float | None
    completed_at: float | None

    def as_json(self) -> dict[str, object]:
        return asdict(self)


def clean_http_url(value: str) -> str:
    url = value.strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("browser task URL must use HTTP(S)")
    if len(url) > 4000:
        raise ValueError("browser task URL is too long")
    return url


def entry_page_url(page_url: str) -> str:
    parsed = urlparse(page_url)
    path = parsed.path.rstrip("/")
    if path.endswith("/download"):
        path = path[: -len("/download")] or "/"
        return urlunparse(parsed._replace(path=path, query="", fragment=""))
    return page_url


def package_suffix(download_url: str) -> str:
    marker = urlparse(download_url).path.casefold()
    return ".xapk" if "/xapk/" in marker else ".apk"


def xpath_literal(value: str) -> str:
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    parts = value.split("'")
    return "concat(" + ", \"'\", ".join(f"'{part}'" for part in parts) + ")"


class BrowserDownloadStore:
    """SQLite queue shared by Agent processes and the LAN browser worker."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path.resolve(strict=False)

    def initialize(self, *, recover: bool = True) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS browser_download_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_page_url TEXT NOT NULL,
                    page_url TEXT NOT NULL,
                    download_url TEXT NOT NULL,
                    suffix TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    progress REAL NOT NULL DEFAULT 0,
                    received_bytes INTEGER NOT NULL DEFAULT 0,
                    total_bytes INTEGER NOT NULL DEFAULT 0,
                    result_path TEXT NOT NULL DEFAULT '',
                    final_url TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    started_at REAL,
                    completed_at REAL,
                    CHECK (
                        status IN (
                            'pending', 'navigating', 'verifying',
                            'downloading', 'completed', 'failed'
                        )
                    )
                );
                CREATE INDEX IF NOT EXISTS browser_tasks_status_created
                    ON browser_download_tasks(status, created_at, id);
                CREATE TABLE IF NOT EXISTS browser_worker_state (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    status TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    current_task_id INTEGER,
                    heartbeat_at REAL NOT NULL,
                    chrome_port INTEGER NOT NULL,
                    profile_path TEXT NOT NULL
                );
                """
            )
            if recover:
                now = time.time()
                connection.execute(
                    """
                    UPDATE browser_download_tasks
                    SET status = 'pending',
                        detail = '服务重启后继续',
                        updated_at = ?,
                        started_at = NULL
                    WHERE status IN ('navigating', 'verifying', 'downloading')
                    """,
                    (now,),
                )

    def submit(
        self,
        page_url: str,
        download_url: str,
        *,
        suffix: str | None = None,
    ) -> BrowserDownloadTask:
        page = clean_http_url(page_url)
        download = clean_http_url(download_url)
        selected_suffix = (suffix or package_suffix(download)).casefold()
        if selected_suffix not in {".apk", ".xapk", ".apkm", ".apks"}:
            raise ValueError("unsupported browser download suffix")
        now = time.time()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO browser_download_tasks (
                    entry_page_url, page_url, download_url, suffix,
                    status, detail, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'pending', '等待专用 Chrome', ?, ?)
                """,
                (
                    entry_page_url(page),
                    page,
                    download,
                    selected_suffix,
                    now,
                    now,
                ),
            )
            task_id = int(cursor.lastrowid)
        task = self.get(task_id)
        if task is None:
            raise BrowserWorkerError("browser task was not created")
        return task

    def claim_next(self) -> BrowserDownloadTask | None:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM browser_download_tasks
                WHERE status = 'pending'
                ORDER BY created_at, id
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            now = time.time()
            connection.execute(
                """
                UPDATE browser_download_tasks
                SET status = 'navigating', detail = '正在打开应用详情页',
                    progress = 0, received_bytes = 0, total_bytes = 0,
                    error = '', started_at = ?, updated_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (now, now, row["id"]),
            )
            connection.commit()
        return self.get(int(row["id"]))

    def update(
        self,
        task_id: int,
        *,
        status: str | None = None,
        detail: str | None = None,
        progress: float | None = None,
        received_bytes: int | None = None,
        total_bytes: int | None = None,
    ) -> None:
        assignments = ["updated_at = ?"]
        parameters: list[object] = [time.time()]
        for column, value in (
            ("status", status),
            ("detail", detail),
            ("progress", progress),
            ("received_bytes", received_bytes),
            ("total_bytes", total_bytes),
        ):
            if value is not None:
                assignments.append(f"{column} = ?")
                parameters.append(value)
        parameters.append(task_id)
        with self._connection() as connection:
            connection.execute(
                f"UPDATE browser_download_tasks SET {', '.join(assignments)} WHERE id = ?",
                parameters,
            )

    def complete(
        self,
        task_id: int,
        result_path: Path,
        final_url: str,
        byte_count: int,
    ) -> None:
        now = time.time()
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE browser_download_tasks
                SET status = 'completed', detail = '浏览器下载完成',
                    progress = 100, received_bytes = ?, total_bytes = ?,
                    result_path = ?, final_url = ?, error = '',
                    completed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    byte_count,
                    byte_count,
                    str(result_path),
                    final_url,
                    now,
                    now,
                    task_id,
                ),
            )

    def fail(self, task_id: int, error: str) -> None:
        now = time.time()
        message = " ".join(error.split())[:1000] or "浏览器下载失败"
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE browser_download_tasks
                SET status = 'failed', detail = '下载失败', error = ?,
                    completed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (message, now, now, task_id),
            )

    def get(self, task_id: int) -> BrowserDownloadTask | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM browser_download_tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
        return self._task(row) if row is not None else None

    def set_worker_state(
        self,
        status: str,
        detail: str,
        *,
        current_task_id: int | None,
        chrome_port: int,
        profile_path: Path,
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO browser_worker_state (
                    singleton, status, detail, current_task_id,
                    heartbeat_at, chrome_port, profile_path
                ) VALUES (1, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(singleton) DO UPDATE SET
                    status = excluded.status,
                    detail = excluded.detail,
                    current_task_id = excluded.current_task_id,
                    heartbeat_at = excluded.heartbeat_at,
                    chrome_port = excluded.chrome_port,
                    profile_path = excluded.profile_path
                """,
                (
                    status,
                    detail,
                    current_task_id,
                    time.time(),
                    chrome_port,
                    str(profile_path),
                ),
            )

    def worker_available(self, maximum_age: float = 30.0) -> bool:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT status, heartbeat_at FROM browser_worker_state WHERE singleton = 1"
            ).fetchone()
        return bool(
            row
            and row["status"] not in {"stopped", "unavailable"}
            and time.time() - float(row["heartbeat_at"]) <= maximum_age
        )

    def snapshot(self, limit: int = 10) -> dict[str, object]:
        with self._connection() as connection:
            state = connection.execute(
                "SELECT * FROM browser_worker_state WHERE singleton = 1"
            ).fetchone()
            counts = {
                row["status"]: int(row["count"])
                for row in connection.execute(
                    """
                    SELECT status, COUNT(*) AS count
                    FROM browser_download_tasks
                    GROUP BY status
                    """
                ).fetchall()
            }
            rows = connection.execute(
                """
                SELECT * FROM browser_download_tasks
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (max(1, min(limit, 50)),),
            ).fetchall()
        state_json = dict(state) if state is not None else {
            "status": "stopped",
            "detail": "浏览器 Worker 尚未启动",
            "current_task_id": None,
            "heartbeat_at": 0,
            "chrome_port": 0,
            "profile_path": "",
        }
        state_json["available"] = self.worker_available()
        return {
            "worker": state_json,
            "counts": {status: counts.get(status, 0) for status in TASK_STATUSES},
            "tasks": [self._task(row).as_json() for row in rows],
        }

    @staticmethod
    def _task(row: sqlite3.Row) -> BrowserDownloadTask:
        return BrowserDownloadTask(**dict(row))

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()


class PersistentChromeBackend:
    """Visible, dedicated Chrome instance with a reusable browser profile."""

    def __init__(
        self,
        profile_path: Path,
        download_root: Path,
        *,
        chrome_port: int = 9223,
        chrome_path: Path = CHROME_PATH,
    ) -> None:
        self.profile_path = profile_path.resolve(strict=False)
        self.download_root = download_root.resolve(strict=False)
        self.chrome_port = chrome_port
        self.chrome_path = chrome_path
        self.browser = None

    def ensure_browser(self):
        if self.browser is not None:
            try:
                _ = self.browser.latest_tab
                return self.browser
            except Exception:
                self.browser = None
        if not self.chrome_path.is_file():
            raise BrowserWorkerUnavailable(f"未找到 Google Chrome：{self.chrome_path}")
        try:
            from DrissionPage import Chromium, ChromiumOptions
        except ImportError as error:
            raise BrowserWorkerUnavailable("DrissionPage 尚未安装") from error
        self.profile_path.mkdir(parents=True, exist_ok=True)
        self.download_root.mkdir(parents=True, exist_ok=True)
        options = ChromiumOptions(read_file=False)
        options.set_paths(
            browser_path=str(self.chrome_path),
            local_port=self.chrome_port,
            user_data_path=str(self.profile_path),
            download_path=str(self.download_root),
        )
        options.set_argument("--no-first-run")
        options.set_argument("--no-default-browser-check")
        self.browser = Chromium(options)
        self.browser.set.download_path(str(self.download_root))
        return self.browser

    def download(
        self,
        task: BrowserDownloadTask,
        work_directory: Path,
        update: Callable[..., None],
    ) -> tuple[Path, str, int]:
        browser = self.ensure_browser()
        tab = browser.latest_tab
        work_directory.mkdir(parents=True, exist_ok=True)
        tab.set.download_path(str(work_directory))
        tab.set.when_download_file_exists("overwrite")

        update(status="navigating", detail="正在打开应用详情页")
        tab.get(task.entry_page_url, timeout=45, retry=1)
        if task.entry_page_url != task.page_url:
            update(status="verifying", detail="正在等待详情页并进入下载页")
            detail_link = self._wait_exact_link(
                tab,
                task.page_url,
                timeout=90,
                update=update,
            )
            detail_link.click()
            self._wait_url(tab, task.page_url, timeout=30)

        update(status="verifying", detail="正在等待 ARM 安装包按钮")
        package_link = self._wait_exact_link(
            tab,
            task.download_url,
            timeout=90,
            update=update,
        )
        update(status="downloading", detail="正在通过专用 Chrome 下载")
        mission = package_link.click.to_download(
            save_path=str(work_directory),
            rename=f"package-{task.id}",
            suffix=task.suffix.lstrip("."),
            timeout=60,
        )
        if not mission:
            raise BrowserWorkerError("点击安装包按钮后没有开始下载")

        deadline = time.monotonic() + 900
        while not mission.is_done and time.monotonic() < deadline:
            received = max(0, int(getattr(mission, "received_bytes", 0) or 0))
            total = max(0, int(getattr(mission, "total_bytes", 0) or 0))
            progress = min(99.9, received / total * 100) if total else 0.0
            update(
                status="downloading",
                detail="正在下载安装包",
                progress=round(progress, 1),
                received_bytes=received,
                total_bytes=total,
            )
            time.sleep(1)
        if not mission.is_done:
            mission.cancel()
            raise BrowserWorkerError("浏览器下载超过 15 分钟")
        mission_state = str(getattr(mission, "state", "") or "").casefold()
        if mission_state not in {"done", "completed"}:
            raise BrowserWorkerError(
                f"浏览器下载未完成：{mission_state or 'unknown'}"
            )
        final_path = Path(str(mission.final_path)).resolve(strict=False)
        if not final_path.is_file():
            raise BrowserWorkerError("浏览器未返回完成文件")
        final_url = str(getattr(mission, "url", "") or task.download_url)
        return final_path, final_url, final_path.stat().st_size

    @staticmethod
    def _wait_url(tab, expected_url: str, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        target = expected_url.rstrip("/")
        while time.monotonic() < deadline:
            if str(tab.url).split("#", 1)[0].rstrip("/") == target:
                return
            time.sleep(0.25)
        raise BrowserWorkerError("点击详情页按钮后没有进入下载页")

    @staticmethod
    def _wait_exact_link(tab, expected_url: str, timeout: float, update):
        deadline = time.monotonic() + timeout
        locator = f"xpath://a[@href={xpath_literal(expected_url)}]"
        last_status_at = 0.0
        challenge_seen = False
        while time.monotonic() < deadline:
            element = tab.ele(locator, timeout=1)
            if element:
                return element
            now = time.monotonic()
            if now - last_status_at >= 2:
                title = str(getattr(tab, "title", "") or "").casefold()
                url = str(getattr(tab, "url", "") or "")
                challenge = (
                    "just a moment" in title
                    or "请稍候" in title
                    or "请稍后" in title
                    or "__cf_chl" in url
                )
                if challenge:
                    challenge_seen = True
                    update(
                        status="verifying",
                        detail="请在专用 Chrome 完成一次 Cloudflare 验证",
                    )
                last_status_at = now
            time.sleep(0.25)
        if challenge_seen:
            raise BrowserWorkerError(
                "Cloudflare 验证未完成；请在专用 Chrome 窗口完成一次验证后重试"
            )
        raise BrowserWorkerError("页面中没有出现精确下载按钮")

    def close(self) -> None:
        if self.browser is None:
            return
        try:
            self.browser.quit(timeout=5, force=False)
        except Exception:
            pass
        finally:
            self.browser = None

    def reset_to_idle_page(self) -> None:
        """Keep Chrome alive while clearing a completed or failed task page."""
        if self.browser is None:
            return
        try:
            self.browser.latest_tab.get("about:blank", timeout=5, retry=0)
        except Exception:
            # A later task will reconnect to the fixed debugging port.
            self.browser = None


class BrowserDownloadWorker:
    def __init__(
        self,
        store: BrowserDownloadStore,
        backend: PersistentChromeBackend,
        work_root: Path,
    ) -> None:
        self.store = store
        self.backend = backend
        self.work_root = work_root.resolve(strict=False)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="find-apk-browser-worker",
            daemon=True,
        )
        self._thread.start()

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
        self.backend.close()
        self._state("stopped", "浏览器 Worker 已停止", None)

    def _run(self) -> None:
        self.work_root.mkdir(parents=True, exist_ok=True)
        try:
            self.backend.ensure_browser()
        except Exception as error:
            self._state("unavailable", str(error), None)
        else:
            self._state("idle", "专用 Chrome 已就绪", None)

        while not self._stop.is_set():
            task = self.store.claim_next()
            if task is None:
                self._state("idle", "专用 Chrome 已就绪", None)
                self._stop.wait(1)
                continue
            self._state("running", task.detail, task.id)
            task_directory = self.work_root / str(task.id)
            if task_directory.exists():
                shutil.rmtree(task_directory)
            try:
                result_path, final_url, byte_count = self.backend.download(
                    task,
                    task_directory,
                    lambda **values: self._update_task(task.id, **values),
                )
                self.store.complete(task.id, result_path, final_url, byte_count)
            except Exception as error:
                self.store.fail(task.id, str(error))
            finally:
                self.backend.reset_to_idle_page()
                self._state("idle", "专用 Chrome 已就绪", None)

    def _update_task(self, task_id: int, **values) -> None:
        self.store.update(task_id, **values)
        detail = str(values.get("detail") or "正在处理浏览器任务")
        self._state("running", detail, task_id)

    def _state(
        self,
        status: str,
        detail: str,
        current_task_id: int | None,
    ) -> None:
        self.store.set_worker_state(
            status,
            detail,
            current_task_id=current_task_id,
            chrome_port=self.backend.chrome_port,
            profile_path=self.backend.profile_path,
        )


def default_browser_store(project_root: Path) -> BrowserDownloadStore:
    state_root = Path(
        os.environ.get("FIND_APK_SHARE_STATE", project_root / ".find-apk-share")
    )
    return BrowserDownloadStore(state_root / "browser-downloads.sqlite3")
