#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import sysconfig
import tempfile
import time
from urllib.error import URLError
from urllib.request import urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LABEL = "com.findapk.lan-share"
DOMAIN = f"gui/{os.getuid()}"
SERVICE_TARGET = f"{DOMAIN}/{LABEL}"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
STATE_ROOT = PROJECT_ROOT / ".find-apk-share"
PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"
PYTHON_EXECUTABLE = PYTHON.resolve(strict=False)
VENV_SITE_PACKAGES = Path(sysconfig.get_paths()["purelib"]).resolve(strict=False)
LOG_ROOT = Path.home() / "Library" / "Logs" / "Find-APK"
BROWSER_WORKER_TOOL = PROJECT_ROOT / "tools" / "browser_worker_service.py"


def manage_browser_worker(command: str) -> bool:
    completed = subprocess.run(
        [str(PYTHON_EXECUTABLE), str(BROWSER_WORKER_TOOL), command],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.returncode and completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    return completed.returncode == 0


def service_configuration(port: int) -> dict[str, object]:
    return {
        "Label": LABEL,
        "ProgramArguments": [
            str(PYTHON_EXECUTABLE),
            "-m",
            "uvicorn",
            "lan_share.app:app",
            "--host",
            "0.0.0.0",
            "--port",
            str(port),
            "--app-dir",
            str(PROJECT_ROOT),
        ],
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 5,
        "ProcessType": "Background",
        "StandardOutPath": str(LOG_ROOT / "server.log"),
        "StandardErrorPath": str(LOG_ROOT / "server-error.log"),
        "EnvironmentVariables": {
            "PYTHONUNBUFFERED": "1",
            "FIND_APK_PORT": str(port),
            "FIND_APK_DOWNLOADS": str(PROJECT_ROOT / "downloads"),
            "FIND_APK_SHARE_STATE": str(STATE_ROOT),
            "FIND_APK_BROWSER_PORT": "9223",
            "PYTHONPATH": str(VENV_SITE_PACKAGES),
            "VIRTUAL_ENV": str(PROJECT_ROOT / ".venv"),
        },
    }


def launchctl(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
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
        prefix=f".{LABEL}.",
        suffix=".plist",
        dir=PLIST_PATH.parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as output:
            plistlib.dump(service_configuration(port), output, sort_keys=False)
        os.replace(temporary_name, PLIST_PATH)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def wait_until_healthy(port: int, timeout: float = 45.0) -> bool:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/health"
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return True
        except (OSError, URLError):
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
    launchctl("bootstrap", DOMAIN, str(PLIST_PATH))
    launchctl("enable", SERVICE_TARGET)
    launchctl("kickstart", "-k", SERVICE_TARGET)
    if not wait_until_healthy(port):
        print("Service started but did not become healthy.", file=sys.stderr)
        print(f"Error log: {LOG_ROOT / 'server-error.log'}", file=sys.stderr)
        return 1
    if not manage_browser_worker("install"):
        print("LAN service is running, but the browser worker failed to start.", file=sys.stderr)
        return 1
    print("classification=service_running")
    print(f"label={LABEL}")
    print(f"port={port}")
    print(f"plist={PLIST_PATH}")
    return 0


def start(port: int) -> int:
    if not PLIST_PATH.is_file():
        return install(port)
    if not is_loaded():
        launchctl("bootstrap", DOMAIN, str(PLIST_PATH))
    launchctl("kickstart", "-k", SERVICE_TARGET)
    if not wait_until_healthy(port):
        print("Service did not become healthy.", file=sys.stderr)
        return 1
    if not manage_browser_worker("start"):
        print("LAN service is running, but the browser worker failed to start.", file=sys.stderr)
        return 1
    print("classification=service_running")
    print(f"label={LABEL}")
    print(f"port={port}")
    return 0


def stop() -> int:
    manage_browser_worker("stop")
    if is_loaded():
        launchctl("bootout", SERVICE_TARGET)
    print("classification=service_stopped")
    return 0


def uninstall() -> int:
    stop()
    manage_browser_worker("uninstall")
    PLIST_PATH.unlink(missing_ok=True)
    print("classification=service_uninstalled")
    return 0


def status() -> int:
    loaded = is_loaded()
    print(f"classification={'service_running' if loaded else 'service_stopped'}")
    print(f"label={LABEL}")
    print(f"plist={PLIST_PATH}")
    return 0 if loaded else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manage the persistent Find APK macOS LAN service."
    )
    parser.add_argument(
        "command",
        choices=("install", "start", "stop", "status", "uninstall"),
    )
    parser.add_argument("--port", type=int, default=8765)
    arguments = parser.parse_args()
    if arguments.port < 1 or arguments.port > 65535:
        parser.error("--port must be between 1 and 65535")
    return arguments


def main() -> int:
    arguments = parse_args()
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
