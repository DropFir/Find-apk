#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import sys
import threading
import time


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lan_share.browser_worker import (  # noqa: E402
    active_display_bounds,
    BrowserDownloadStore,
    BrowserDownloadWorker,
    PersistentChromeBackend,
    secondary_display_window,
)


STATE_ROOT = Path(
    os.environ.get("FIND_APK_SHARE_STATE", PROJECT_ROOT / ".find-apk-share")
).resolve(strict=False)
CHROME_PORT = int(os.environ.get("FIND_APK_BROWSER_PORT", "9223"))
STATUS_PATH = PROJECT_ROOT / "lan_share" / "static" / "browser-worker-status.json"


def write_status_snapshot(store: BrowserDownloadStore) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATUS_PATH.with_name(f".{STATUS_PATH.name}.tmp")
    temporary.write_text(
        json.dumps(store.snapshot(limit=10), ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(temporary, STATUS_PATH)


def main() -> int:
    store = BrowserDownloadStore(STATE_ROOT / "browser-downloads.sqlite3")
    store.initialize(recover=True)
    backend = PersistentChromeBackend(
        STATE_ROOT / "browser-profile",
        STATE_ROOT / "browser-downloads" / "temporary",
        chrome_port=CHROME_PORT,
        window_bounds=secondary_display_window(active_display_bounds()),
    )
    worker = BrowserDownloadWorker(
        store,
        backend,
        STATE_ROOT / "browser-downloads" / "jobs",
    )
    stop = threading.Event()

    def request_stop(_signum, _frame) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    worker.start()
    try:
        while not stop.wait(1):
            if not worker.is_running:
                raise RuntimeError("browser worker thread stopped unexpectedly")
            write_status_snapshot(store)
    finally:
        worker.stop()
        write_status_snapshot(store)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
