from __future__ import annotations

import os
from pathlib import Path
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lan_share.browser_worker import (  # noqa: E402
    BrowserDownloadStore,
    BrowserWorkerError,
    BrowserWorkerUnavailable,
)


STATE_ROOT = Path(
    os.environ.get("FIND_APK_SHARE_STATE", PROJECT_ROOT / ".find-apk-share")
).resolve(strict=False)
STORE_PATH = STATE_ROOT / "browser-downloads.sqlite3"


def persistent_browser_available() -> bool:
    if not STORE_PATH.is_file():
        return False
    store = BrowserDownloadStore(STORE_PATH)
    try:
        return store.worker_available()
    except OSError:
        return False


def download_package_with_persistent_browser(
    page_url: str,
    download_url: str,
    *,
    suffix: str,
    timeout: float = 960,
) -> tuple[Path, str, int]:
    if timeout <= 0 or timeout > 1800:
        raise ValueError("persistent browser timeout must be between 1 and 1800 seconds")
    store = BrowserDownloadStore(STORE_PATH)
    store.initialize(recover=False)
    if not store.worker_available():
        raise BrowserWorkerUnavailable("专用 Chrome Worker 当前不可用")
    task = store.submit(page_url, download_url, suffix=suffix)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = store.get(task.id)
        if current is None:
            raise BrowserWorkerError("浏览器下载任务记录丢失")
        if current.status == "completed":
            path = Path(current.result_path).resolve(strict=False)
            if not path.is_file():
                raise BrowserWorkerError("浏览器任务已完成但文件不存在")
            return path, current.final_url, path.stat().st_size
        if current.status == "failed":
            raise BrowserWorkerError(current.error or "专用 Chrome 下载失败")
        time.sleep(0.5)
    raise BrowserWorkerError("等待专用 Chrome 下载超时")


__all__ = [
    "BrowserWorkerError",
    "BrowserWorkerUnavailable",
    "download_package_with_persistent_browser",
    "persistent_browser_available",
]
