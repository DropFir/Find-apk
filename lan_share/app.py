from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import date as CalendarDate
from functools import lru_cache
from html.parser import HTMLParser
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import time
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode, urlparse
from urllib.request import Request as UrlRequest, urlopen

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from lan_share.bundles import create_delivery_bundle, remove_delivery_directory
from lan_share.browser_worker import BrowserDownloadStore
from lan_share.codex_controller import CodexController
from lan_share.error_reports import (
    clean_error_filename,
    clean_error_reason,
    ErrorApkStore,
)
from lan_share.external_monitor import ExternalProductionMonitor
from lan_share.indexer import DeliveryIndex
from lan_share.production_queue import ProductionQueue
from lan_share.queue_store import (
    is_cloudflare_blocked_retry,
    KeywordQueue,
    QUEUE_STATUSES,
    SKIPPED_STATUSES,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOWNLOADS_ROOT = Path(
    os.environ.get("FIND_APK_DOWNLOADS", PROJECT_ROOT / "downloads")
).resolve(strict=False)
STATE_ROOT = Path(
    os.environ.get("FIND_APK_SHARE_STATE", PROJECT_ROOT / ".find-apk-share")
).resolve(strict=False)
REFRESH_SECONDS = max(5, int(os.environ.get("FIND_APK_REFRESH_SECONDS", "15")))
PRODUCTION_MONITOR_URL = os.environ.get(
    "FIND_APK_PRODUCTION_MONITOR_URL",
    "http://192.168.5.125:8088/",
)
APKBA_MONITOR_URL = PRODUCTION_MONITOR_URL.rstrip("/")
PRODUCTION_MONITOR_SECONDS = max(
    15,
    int(os.environ.get("FIND_APK_PRODUCTION_MONITOR_SECONDS", "30")),
)
ERROR_APK_MAX_BYTES = max(
    1024 * 1024,
    int(os.environ.get("FIND_APK_ERROR_MAX_BYTES", str(6 * 1024 ** 3))),
)
ERROR_APK_FREE_RESERVE = 2 * 1024 ** 3

index = DeliveryIndex(
    downloads_root=DOWNLOADS_ROOT,
    database_path=STATE_ROOT / "index.sqlite3",
    validator_path=PROJECT_ROOT / "tools" / "validate_delivery.py",
)
keyword_queue = KeywordQueue(STATE_ROOT / "queue.sqlite3")
production_queue = ProductionQueue(STATE_ROOT / "production.sqlite3")
external_monitor = ExternalProductionMonitor(PRODUCTION_MONITOR_URL)
error_apk_store = ErrorApkStore(
    STATE_ROOT / "error-apks.sqlite3",
    STATE_ROOT / "error-apks" / "files",
)
codex_controller = CodexController(
    PROJECT_ROOT,
    STATE_ROOT / "codex-controller.json",
)
browser_download_store = BrowserDownloadStore(
    STATE_ROOT / "browser-downloads.sqlite3"
)
delivery_locks: dict[int, asyncio.Lock] = {}
production_cleanup_lock = asyncio.Lock()


PACKAGE_NAME_PATH_SEGMENT = re.compile(
    r"(?:^|/)([A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+){2,})(?:/|$)"
)
GOOGLE_ICON_HOSTS = {
    "lh3.googleusercontent.com",
    "play-lh.googleusercontent.com",
}


class OpenGraphImageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.image_url = ""

    def handle_starttag(self, tag: str, attrs) -> None:
        if self.image_url or tag.casefold() != "meta":
            return
        values = {str(name).casefold(): str(value) for name, value in attrs}
        marker = values.get("property", "").casefold()
        if marker == "og:image":
            self.image_url = values.get("content", "").strip()


def candidate_package_name(candidate_url: str) -> str:
    try:
        path = unquote(urlparse(candidate_url).path)
    except ValueError:
        return ""
    matches = PACKAGE_NAME_PATH_SEGMENT.findall(path)
    return matches[-1] if matches else ""


def parse_open_graph_image(page: str) -> str:
    parser = OpenGraphImageParser()
    parser.feed(page)
    return parser.image_url


@lru_cache(maxsize=512)
def google_play_icon_url(package_name: str) -> str:
    if not PACKAGE_NAME_PATH_SEGMENT.fullmatch(f"/{package_name}/"):
        return ""
    url = "https://play.google.com/store/apps/details?" + urlencode(
        {"id": package_name, "hl": "zh-CN", "gl": "US"}
    )
    request = UrlRequest(
        url,
        headers={
            "Accept": "text/html,*/*;q=0.8",
            "User-Agent": "Mozilla/5.0 Find-APK-LAN-Console/1.0",
        },
    )
    try:
        with urlopen(request, timeout=8) as response:
            page = response.read(2 * 1024 * 1024).decode("utf-8", errors="replace")
    except (HTTPError, URLError, OSError):
        return ""
    image_url = parse_open_graph_image(page)
    parsed = urlparse(image_url)
    if parsed.scheme != "https" or parsed.hostname not in GOOGLE_ICON_HOSTS:
        return ""
    return image_url


def fetch_apkba_resource(url: str) -> tuple[int, str, bytes]:
    request = UrlRequest(
        url,
        headers={
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
            "User-Agent": "Find-APK-LAN-Console/1.0",
        },
    )
    try:
        with urlopen(request, timeout=15) as response:
            return (
                response.status,
                response.headers.get("Content-Type", "application/octet-stream"),
                response.read(),
            )
    except HTTPError as error:
        return (
            error.code,
            error.headers.get("Content-Type", "application/json"),
            error.read(),
        )


def rewrite_apkba_monitor_html(content: bytes) -> str:
    page = content.decode("utf-8", errors="replace")
    return page.replace(
        "fetch('/api/summary?date='",
        "fetch('/api/apkba-summary?date='",
    )


def storage_status(path: Path) -> dict[str, int | float]:
    usage = shutil.disk_usage(path)
    percent = (usage.used / usage.total * 100) if usage.total else 0.0
    return {
        "total": usage.total,
        "used": usage.used,
        "free": usage.free,
        "percent": round(percent, 1),
    }


def delivery_directory_storage_bytes(directory: Path) -> int:
    """Return regular-file bytes held by one local delivery directory."""
    total = 0
    for current_root, _, filenames in os.walk(directory, followlinks=False):
        for filename in filenames:
            try:
                file_status = (Path(current_root) / filename).stat(
                    follow_symlinks=False
                )
            except OSError:
                continue
            if stat.S_ISREG(file_status.st_mode):
                total += file_status.st_size
    return total


def production_storage_summary(
    candidates: list[dict[str, str]],
    *,
    downloads_root: Path = DOWNLOADS_ROOT,
    bundles_root: Path | None = None,
) -> dict[str, int]:
    """Summarize real, currently occupied storage for production cleanup."""
    root = downloads_root.resolve(strict=False)
    directories = sorted({item["directory"] for item in candidates})
    existing_directories = 0
    delivery_bytes = 0
    for directory in directories:
        target = (root / directory).resolve(strict=False)
        try:
            target.relative_to(root)
        except ValueError:
            continue
        if not target.is_dir() or target.is_symlink():
            continue
        existing_directories += 1
        delivery_bytes += delivery_directory_storage_bytes(target)

    temporary_root = bundles_root or STATE_ROOT / "bundles"
    temporary_files = 0
    temporary_bytes = 0
    if temporary_root.is_dir():
        for bundle in temporary_root.glob("*.zip"):
            try:
                bundle_status = bundle.stat(follow_symlinks=False)
            except OSError:
                continue
            if stat.S_ISREG(bundle_status.st_mode):
                temporary_files += 1
                temporary_bytes += bundle_status.st_size

    return {
        "directories": existing_directories,
        "bytes": delivery_bytes,
        "temporary_files": temporary_files,
        "temporary_bytes": temporary_bytes,
    }


class KeywordSubmission(BaseModel):
    keywords: list[str] = Field(min_length=1)


class ManualNotFoundSubmission(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    category: Literal["ios", "paid", "not_found"] = "not_found"


class ReopenKeywordSubmission(BaseModel):
    reason: str = Field(default="", max_length=500)
    candidate_url: str = Field(default="", max_length=2000)


class CodexControllerSettingsSubmission(BaseModel):
    enabled: bool
    model: str = Field(min_length=1, max_length=80)
    effort: Literal["low", "medium", "high", "xhigh", "max"]
    interval_minutes: int = Field(ge=10, le=720)
    batch_size: int = Field(ge=1, le=10)
    workers: int = Field(ge=1, le=4)


async def refresh_forever(stop: asyncio.Event) -> None:
    while not stop.is_set():
        await asyncio.to_thread(index.scan)
        try:
            await asyncio.wait_for(stop.wait(), timeout=REFRESH_SECONDS)
        except asyncio.TimeoutError:
            pass


async def monitor_external_forever(stop: asyncio.Event) -> None:
    while not stop.is_set():
        deliveries = await asyncio.to_thread(index.production_candidates)
        await asyncio.to_thread(
            external_monitor.check,
            deliveries,
            production_queue,
        )
        try:
            await asyncio.wait_for(
                stop.wait(),
                timeout=PRODUCTION_MONITOR_SECONDS,
            )
        except asyncio.TimeoutError:
            pass


async def codex_controller_forever(stop: asyncio.Event) -> None:
    while not stop.is_set():
        await asyncio.to_thread(codex_controller.tick)
        try:
            await asyncio.wait_for(stop.wait(), timeout=15)
        except asyncio.TimeoutError:
            pass


@asynccontextmanager
async def lifespan(_: FastAPI):
    index.initialize()
    keyword_queue.initialize()
    production_queue.initialize()
    error_apk_store.initialize()
    browser_download_store.initialize(recover=False)
    stop = asyncio.Event()
    refresh_task = asyncio.create_task(refresh_forever(stop))
    monitor_task = asyncio.create_task(monitor_external_forever(stop))
    codex_task = asyncio.create_task(codex_controller_forever(stop))
    try:
        yield
    finally:
        stop.set()
        await asyncio.gather(refresh_task, monitor_task, codex_task)
        await asyncio.to_thread(codex_controller.shutdown)


app = FastAPI(
    title="Find APK",
    description="Search and download completed Find-APK deliveries on the local network.",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)

templates = Jinja2Templates(directory=PROJECT_ROOT / "lan_share" / "templates")
app.mount(
    "/static",
    StaticFiles(directory=PROJECT_ROOT / "lan_share" / "static"),
    name="static",
)


@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={},
    )


@app.get("/apkba-monitor", response_class=HTMLResponse)
async def apkba_monitor():
    try:
        status_code, _, content = await asyncio.to_thread(
            fetch_apkba_resource,
            f"{APKBA_MONITOR_URL}/",
        )
    except (OSError, URLError) as error:
        raise HTTPException(
            status_code=502,
            detail="APKBA 制作站当前无法连接",
        ) from error
    if status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"APKBA 制作站返回 HTTP {status_code}",
        )
    return HTMLResponse(
        rewrite_apkba_monitor_html(content),
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/apkba-summary")
async def apkba_summary(
    date: str = Query(default="", max_length=10, pattern=r"^\d{4}-\d{2}-\d{2}$"),
):
    target = f"{APKBA_MONITOR_URL}/api/summary?{urlencode({'date': date})}"
    try:
        status_code, content_type, content = await asyncio.to_thread(
            fetch_apkba_resource,
            target,
        )
    except (OSError, URLError) as error:
        raise HTTPException(
            status_code=502,
            detail="APKBA 制作站当前无法连接",
        ) from error
    return Response(
        content=content,
        status_code=status_code,
        media_type=content_type.split(";", 1)[0],
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/search")
async def search(
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=100, ge=1, le=200),
):
    return {
        "query": q,
        "items": await asyncio.to_thread(index.search_json, q, limit=limit),
    }


@app.get("/api/status")
async def status():
    payload = await asyncio.to_thread(index.status)
    payload["storage"] = await asyncio.to_thread(
        storage_status,
        DOWNLOADS_ROOT,
    )
    return payload


@app.get("/api/codex-controller")
async def codex_controller_status():
    return await asyncio.to_thread(codex_controller.snapshot)


@app.get("/api/browser-worker")
async def browser_worker_status():
    return await asyncio.to_thread(browser_download_store.snapshot, 10)


@app.put("/api/codex-controller/settings")
async def codex_controller_settings(
    submission: CodexControllerSettingsSubmission,
):
    try:
        return await asyncio.to_thread(
            codex_controller.configure,
            submission.model_dump(),
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/codex-controller/run")
async def codex_controller_run():
    return await asyncio.to_thread(codex_controller.run_now)


@app.post("/api/codex-controller/stop")
async def codex_controller_stop():
    return await asyncio.to_thread(codex_controller.stop_running)


@app.get("/api/error-apks")
async def error_apk_reports():
    items = await asyncio.to_thread(error_apk_store.list, limit=200)
    return {
        "count": await asyncio.to_thread(error_apk_store.count),
        "items": [item.as_json() for item in items],
        "max_upload_bytes": ERROR_APK_MAX_BYTES,
    }


@app.post("/api/error-apks")
async def submit_error_apk(
    request: Request,
    filename: str = Query(min_length=1, max_length=300),
    reason: str = Query(min_length=1, max_length=2500),
):
    try:
        original_name = clean_error_filename(filename)
        cleaned_reason = clean_error_reason(reason)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    content_length = request.headers.get("content-length", "")
    if content_length:
        try:
            expected_size = int(content_length)
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail="Invalid upload size",
            ) from error
        if expected_size > ERROR_APK_MAX_BYTES:
            raise HTTPException(status_code=413, detail="ZIP file is too large")
        free = shutil.disk_usage(STATE_ROOT).free
        if expected_size > max(0, free - ERROR_APK_FREE_RESERVE):
            raise HTTPException(
                status_code=507,
                detail="Not enough free disk space for this ZIP",
            )

    stored_name = f"{int(time.time())}-{secrets.token_hex(8)}.zip"
    final_path = error_apk_store.files_root / stored_name
    partial_path = error_apk_store.files_root / f".{stored_name}.part"
    total = 0
    prefix = b""
    try:
        with partial_path.open("xb") as output:
            async for chunk in request.stream():
                if not chunk:
                    continue
                total += len(chunk)
                if total > ERROR_APK_MAX_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="ZIP file is too large",
                    )
                if len(prefix) < 4:
                    prefix += chunk[: 4 - len(prefix)]
                output.write(chunk)
        if total == 0 or not prefix.startswith(b"PK"):
            raise HTTPException(
                status_code=400,
                detail="Uploaded file is not a ZIP archive",
            )
        os.replace(partial_path, final_path)
        report = await asyncio.to_thread(
            error_apk_store.add,
            original_name=original_name,
            stored_name=stored_name,
            reason=cleaned_reason,
            size=total,
        )
    except HTTPException:
        partial_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        raise
    except OSError as error:
        partial_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=507,
            detail="ZIP file could not be saved",
        ) from error
    except Exception:
        partial_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        raise
    return {"item": report.as_json()}


@app.get("/api/error-apks/{report_id}/download")
async def download_error_apk(report_id: int):
    resolved = await asyncio.to_thread(error_apk_store.resolve_file, report_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail="Error APK report not found")
    path, original_name = resolved
    return FileResponse(
        path,
        media_type="application/zip",
        filename=original_name,
        headers={"Cache-Control": "private, no-store"},
    )


@app.get("/api/keywords")
async def keyword_jobs(
    status: str | None = Query(default=None),
    q: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    if status is not None and status not in (*QUEUE_STATUSES, "skipped"):
        raise HTTPException(status_code=400, detail="Unsupported queue status")
    counts = (await asyncio.to_thread(keyword_queue.snapshot, limit=1))[
        "counts"
    ]
    offset = (page - 1) * page_size
    if status == "skipped":
        jobs = await asyncio.to_thread(
            keyword_queue.list_jobs_for_statuses,
            SKIPPED_STATUSES,
            query=q,
            limit=page_size,
            offset=offset,
        )
        total = await asyncio.to_thread(
            keyword_queue.count_jobs,
            statuses=SKIPPED_STATUSES,
            query=q,
        )
    else:
        jobs = await asyncio.to_thread(
            keyword_queue.list_jobs,
            status=status,
            query=q,
            limit=page_size,
            offset=offset,
        )
        total = await asyncio.to_thread(
            keyword_queue.count_jobs,
            status=status,
            query=q,
        )
    total_pages = max(1, (total + page_size - 1) // page_size)
    snapshot = {
        "counts": counts,
        "query": q,
        "items": [job.as_json() for job in jobs],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
        },
    }
    return snapshot


@app.get("/api/cloudflare-blocked")
async def cloudflare_blocked_jobs(
    q: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    offset = (page - 1) * page_size
    jobs = await asyncio.to_thread(
        keyword_queue.list_cloudflare_blocked,
        query=q,
        limit=page_size,
        offset=offset,
    )
    total = await asyncio.to_thread(
        keyword_queue.count_cloudflare_blocked,
        query=q,
    )
    items = []
    for job in jobs:
        item = job.as_json()
        package_name = candidate_package_name(job.candidate_url)
        item["package_name"] = package_name
        item["candidate_host"] = urlparse(job.candidate_url).hostname or ""
        item["icon_url"] = (
            f"/api/cloudflare-blocked/{job.id}/icon" if package_name else ""
        )
        items.append(item)
    total_pages = max(1, (total + page_size - 1) // page_size)
    return {
        "items": items,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
        },
    }


@app.get("/api/cloudflare-blocked/{job_id}/icon")
async def cloudflare_blocked_icon(job_id: int):
    job = await asyncio.to_thread(keyword_queue.get, job_id)
    if job is None or not is_cloudflare_blocked_retry(job):
        raise HTTPException(status_code=404, detail="Blocked candidate not found")
    package_name = candidate_package_name(job.candidate_url)
    icon_url = await asyncio.to_thread(google_play_icon_url, package_name)
    if not icon_url:
        raise HTTPException(status_code=404, detail="App icon not found")
    return RedirectResponse(
        icon_url,
        status_code=307,
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.post("/api/keywords")
async def add_keywords(submission: KeywordSubmission):
    result = await asyncio.to_thread(keyword_queue.add, submission.keywords)
    result["queue"] = await asyncio.to_thread(keyword_queue.snapshot, limit=1)
    return result


@app.post("/api/keywords/{job_id}/manual-not-found")
async def confirm_keyword_not_found(
    job_id: int,
    submission: ManualNotFoundSubmission,
):
    try:
        job = await asyncio.to_thread(
            keyword_queue.confirm_not_found,
            job_id,
            reason=submission.reason,
            category=submission.category,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Keyword job not found") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {
        "item": job.as_json(),
        "counts": (
            await asyncio.to_thread(keyword_queue.snapshot, limit=1)
        )["counts"],
    }


@app.post("/api/keywords/{job_id}/skipped-reason")
async def update_keyword_skipped_reason(
    job_id: int,
    submission: ManualNotFoundSubmission,
):
    try:
        job = await asyncio.to_thread(
            keyword_queue.update_skipped_reason,
            job_id,
            reason=submission.reason,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Keyword job not found") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"item": job.as_json()}


@app.post("/api/keywords/{job_id}/reopen")
async def reopen_keyword_job(
    job_id: int,
    submission: ReopenKeywordSubmission,
):
    try:
        job = await asyncio.to_thread(
            keyword_queue.reopen,
            job_id,
            reason=submission.reason,
            candidate_url=submission.candidate_url,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Keyword job not found") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {
        "item": job.as_json(),
        "counts": (
            await asyncio.to_thread(keyword_queue.snapshot, limit=1)
        )["counts"],
    }


@app.get("/api/production")
async def production_jobs(
    lane_a_date: CalendarDate | None = Query(default=None),
    lane_b_date: CalendarDate | None = Query(default=None),
):
    deliveries = await asyncio.to_thread(index.production_candidates)
    snapshot = await asyncio.to_thread(
        production_queue.sync_and_list,
        deliveries,
        lane_dates={
            1: (lane_a_date or CalendarDate.today()).isoformat(),
            2: (lane_b_date or CalendarDate.today()).isoformat(),
        },
    )
    for lane in snapshot["lanes"].values():
        for item in lane:
            item["download_url"] = f"/production/download/{item['id']}"
    cleanup_candidates = await asyncio.to_thread(
        production_queue.downloaded_removal_candidates
    )
    snapshot["storage"] = await asyncio.to_thread(
        production_storage_summary,
        cleanup_candidates,
    )
    snapshot["monitor"] = external_monitor.status()
    return snapshot


@app.get("/api/production/cleanup-downloaded")
async def production_cleanup_preview():
    candidates = await asyncio.to_thread(
        production_queue.downloaded_removal_candidates
    )
    summary = await asyncio.to_thread(production_storage_summary, candidates)
    return {"count": len(candidates), **summary}


@app.delete("/api/production/cleanup-downloaded")
async def production_cleanup_downloaded():
    async with production_cleanup_lock:
        candidates = await asyncio.to_thread(
            production_queue.downloaded_removal_candidates
        )
        grouped: dict[str, list[dict[str, str]]] = {}
        for candidate in candidates:
            grouped.setdefault(candidate["directory"], []).append(candidate)

        indexed = await asyncio.to_thread(index.production_candidates)
        delivery_ids_by_directory: dict[str, set[int]] = {}
        for item in indexed:
            directory = str(item["directory"])
            delivery_ids_by_directory.setdefault(directory, set()).add(
                int(item["id"])
            )

        removed_deliveries = 0
        removed_directories = 0
        freed_bytes = 0
        failures: list[dict[str, str]] = []
        for directory, deliveries in grouped.items():
            locks = [
                delivery_lock(delivery_id)
                for delivery_id in sorted(
                    delivery_ids_by_directory.get(directory, set())
                )
            ]
            for lock in locks:
                await lock.acquire()
            try:
                target = DOWNLOADS_ROOT / directory
                directory_bytes = await asyncio.to_thread(
                    delivery_directory_storage_bytes,
                    target,
                )
                existed = await asyncio.to_thread(
                    remove_delivery_directory,
                    target,
                    DOWNLOADS_ROOT,
                )
                recorded = await asyncio.to_thread(
                    production_queue.record_removed_downloads,
                    deliveries,
                )
                removed_deliveries += recorded
                if existed:
                    removed_directories += 1
                    freed_bytes += directory_bytes
            except (KeyError, OSError, ValueError) as error:
                failures.append(
                    {"directory": directory, "detail": str(error)}
                )
            finally:
                for lock in reversed(locks):
                    lock.release()

        await asyncio.to_thread(index.scan)
        return {
            "removed": removed_deliveries,
            "directories": removed_directories,
            "freed_bytes": freed_bytes,
            "failed": len(failures),
            "failures": failures[:20],
        }


def delivery_lock(delivery_id: int) -> asyncio.Lock:
    lock = delivery_locks.get(delivery_id)
    if lock is None:
        lock = asyncio.Lock()
        delivery_locks[delivery_id] = lock
    return lock


@app.get("/production/download/{delivery_id}")
async def production_download(delivery_id: int):
    async with delivery_lock(delivery_id):
        record = await asyncio.to_thread(index.resolve_production_record, delivery_id)
        files = await asyncio.to_thread(index.resolve_delivery_files, delivery_id)
        deliveries = await asyncio.to_thread(index.production_candidates)
        await asyncio.to_thread(production_queue.sync_and_list, deliveries)
        if record is None or files is None:
            raise HTTPException(status_code=404, detail="Delivery not found")
        try:
            path = await asyncio.to_thread(
                create_delivery_bundle,
                files,
                STATE_ROOT / "bundles",
            )
        except OSError as error:
            raise HTTPException(
                status_code=503,
                detail="Delivery archive could not be prepared",
            ) from error
        marked = await asyncio.to_thread(
            production_queue.mark_downloaded,
            record["delivery_key"],
        )
        if not marked:
            path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=409,
                detail="Delivery is not in today's production queue",
            )
    return FileResponse(
        path,
        media_type="application/zip",
        filename=f"{files.directory_name}.zip",
        headers={"Cache-Control": "private, no-store"},
        background=BackgroundTask(path.unlink, missing_ok=True),
    )


@app.get("/icon/{delivery_id}")
async def icon(delivery_id: int):
    path = await asyncio.to_thread(index.resolve_file, delivery_id, "icon")
    if path is None:
        raise HTTPException(status_code=404, detail="Icon not found")
    return FileResponse(
        path,
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/download/{delivery_id}")
async def download(delivery_id: int):
    async with delivery_lock(delivery_id):
        files = await asyncio.to_thread(index.resolve_delivery_files, delivery_id)
        if files is None:
            raise HTTPException(status_code=404, detail="Delivery not found")
        try:
            path = await asyncio.to_thread(
                create_delivery_bundle,
                files,
                STATE_ROOT / "bundles",
            )
        except OSError as error:
            raise HTTPException(
                status_code=503,
                detail="Delivery archive could not be prepared",
            ) from error
    return FileResponse(
        path,
        media_type="application/zip",
        filename=f"{files.directory_name}.zip",
        headers={"Cache-Control": "private, no-store"},
        background=BackgroundTask(path.unlink, missing_ok=True),
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
