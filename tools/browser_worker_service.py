#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import plistlib
import subprocess
import sys
import sysconfig
import tempfile
import time


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
LABEL = "com.findapk.browser-worker"
DOMAIN = f"gui/{os.getuid()}"
SERVICE_TARGET = f"{DOMAIN}/{LABEL}"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
STATE_ROOT = PROJECT_ROOT / ".find-apk-share"
PYTHON = (PROJECT_ROOT / ".venv" / "bin" / "python").resolve(strict=False)
VENV_SITE_PACKAGES = Path(sysconfig.get_paths()["purelib"]).resolve(strict=False)
LOG_ROOT = Path.home() / "Library" / "Logs" / "Find-APK"


def service_configuration(port: int = 9223) -> dict[str, object]:
    return {
        "Label": LABEL,
        "ProgramArguments": [
            str(PYTHON),
            str(PROJECT_ROOT / "tools" / "browser_worker_daemon.py"),
        ],
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 5,
        "ProcessType": "Interactive",
        "StandardOutPath": str(LOG_ROOT / "browser-worker.log"),
        "StandardErrorPath": str(LOG_ROOT / "browser-worker-error.log"),
        "EnvironmentVariables": {
            "PYTHONUNBUFFERED": "1",
            "FIND_APK_SHARE_STATE": str(STATE_ROOT),
            "FIND_APK_BROWSER_PORT": str(port),
            "PYTHONPATH": str(VENV_SITE_PACKAGES),
            "VIRTUAL_ENV": str(PROJECT_ROOT / ".venv"),
        },
    }


def launchctl(*arguments: str, check: bool = True):
    return subprocess.run(
        ["launchctl", *arguments],
        check=check,
        capture_output=True,
        text=True,
    )


def is_loaded() -> bool:
    return launchctl("print", SERVICE_TARGET, check=False).returncode == 0


def write_plist(port: int) -> None:
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{LABEL}.", suffix=".plist", dir=PLIST_PATH.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as output:
            plistlib.dump(service_configuration(port), output, sort_keys=False)
        os.replace(temporary_name, PLIST_PATH)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def wait_until_ready(timeout: float = 30, *, newer_than: float = 0) -> bool:
    database = STATE_ROOT / "browser-downloads.sqlite3"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if database.is_file():
            try:
                from lan_share.browser_worker import BrowserDownloadStore

                store = BrowserDownloadStore(database)
                snapshot = store.snapshot(limit=1)
                heartbeat = float(snapshot["worker"].get("heartbeat_at") or 0)
                if store.worker_available() and heartbeat >= newer_than:
                    return True
            except (OSError, RuntimeError):
                pass
        time.sleep(0.25)
    return False


def install(port: int) -> int:
    if not PYTHON.is_file():
        print(f"Python environment is missing: {PYTHON}", file=sys.stderr)
        return 2
    if is_loaded():
        launchctl("bootout", SERVICE_TARGET, check=False)
    write_plist(port)
    started_at = time.time()
    launchctl("bootstrap", DOMAIN, str(PLIST_PATH))
    launchctl("enable", SERVICE_TARGET)
    # RunAtLoad starts the process after bootstrap.  A simultaneous kickstart can
    # return EX_TEMPFAIL (37) while launchd is already starting the job.
    if not wait_until_ready(timeout=3, newer_than=started_at):
        launchctl("kickstart", "-k", SERVICE_TARGET, check=False)
    if not wait_until_ready(newer_than=started_at):
        print("Browser worker did not become ready.", file=sys.stderr)
        return 1
    print("classification=browser_worker_running")
    print(f"port={port}")
    print(f"profile={STATE_ROOT / 'browser-profile'}")
    return 0


def start(port: int) -> int:
    if not PLIST_PATH.is_file():
        return install(port)
    started_at = time.time()
    loaded = is_loaded()
    if not loaded:
        launchctl("bootstrap", DOMAIN, str(PLIST_PATH))
    elif wait_until_ready(timeout=1, newer_than=started_at):
        print("classification=browser_worker_running")
        return 0
    if not wait_until_ready(timeout=3, newer_than=started_at):
        launchctl("kickstart", "-k", SERVICE_TARGET, check=False)
    if not wait_until_ready(newer_than=started_at):
        print("Browser worker did not become ready.", file=sys.stderr)
        return 1
    print("classification=browser_worker_running")
    return 0


def stop() -> int:
    if is_loaded():
        launchctl("bootout", SERVICE_TARGET, check=False)
        deadline = time.monotonic() + 10
        while is_loaded() and time.monotonic() < deadline:
            time.sleep(0.1)
    print("classification=browser_worker_stopped")
    return 0


def uninstall() -> int:
    stop()
    PLIST_PATH.unlink(missing_ok=True)
    print("classification=browser_worker_uninstalled")
    return 0


def status() -> int:
    running = is_loaded() and wait_until_ready(timeout=2)
    print(f"classification={'browser_worker_running' if running else 'browser_worker_stopped'}")
    return 0 if running else 1


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Manage the persistent Chrome worker.")
    parser.add_argument(
        "command", choices=("install", "start", "stop", "status", "uninstall")
    )
    parser.add_argument("--port", type=int, default=9223)
    arguments = parser.parse_args()
    if sys.platform != "darwin":
        print("This service manager is only available on macOS.", file=sys.stderr)
        return 2
    if arguments.command == "install":
        return install(arguments.port)
    if arguments.command == "start":
        return start(arguments.port)
    if arguments.command == "stop":
        return stop()
    if arguments.command == "uninstall":
        return uninstall()
    return status()


if __name__ == "__main__":
    raise SystemExit(main())
