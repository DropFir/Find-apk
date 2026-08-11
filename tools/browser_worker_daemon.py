#!/usr/bin/env python3
from __future__ import annotations

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
    BrowserDownloadStore,
    BrowserDownloadWorker,
    PersistentChromeBackend,
)


STATE_ROOT = Path(
    os.environ.get("FIND_APK_SHARE_STATE", PROJECT_ROOT / ".find-apk-share")
).resolve(strict=False)
CHROME_PORT = int(os.environ.get("FIND_APK_BROWSER_PORT", "9223"))


def main() -> int:
    store = BrowserDownloadStore(STATE_ROOT / "browser-downloads.sqlite3")
    store.initialize(recover=True)
    backend = PersistentChromeBackend(
        STATE_ROOT / "browser-profile",
        STATE_ROOT / "browser-downloads" / "temporary",
        chrome_port=CHROME_PORT,
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
    finally:
        worker.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
