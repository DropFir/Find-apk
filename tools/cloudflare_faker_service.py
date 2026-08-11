#!/usr/bin/env python3
"""Install and manage Cloudflare-Faker as a persistent macOS LaunchAgent."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import time


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LABEL = "com.dropfir.findapk.cloudflare-faker"
DOMAIN = f"gui/{os.getuid()}"
SERVICE_TARGET = f"{DOMAIN}/{LABEL}"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
RUNTIME_ROOT = PROJECT_ROOT / "tools" / "vendor" / "runtime"
JAVA = RUNTIME_ROOT / "jdk24" / "Contents" / "Home" / "bin" / "java"
JAR = (
    PROJECT_ROOT
    / "tools"
    / "vendor"
    / "Cloudflare-Faker"
    / "target"
    / "Cloudflare-Faker-0.0.1-SNAPSHOT.jar"
)
LOG_PATH = RUNTIME_ROOT / "cloudflare-faker.launch.log"
ERROR_LOG_PATH = RUNTIME_ROOT / "cloudflare-faker.launch.err"


def service_configuration() -> dict[str, object]:
    return {
        "Label": LABEL,
        "ProgramArguments": [
            str(JAVA),
            "--enable-native-access=ALL-UNNAMED",
            "-jar",
            str(JAR),
            "--server.address=127.0.0.1",
            "--server.port=8080",
        ],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "ProcessType": "Background",
        "StandardOutPath": str(LOG_PATH),
        "StandardErrorPath": str(ERROR_LOG_PATH),
        "EnvironmentVariables": {
            "JAVA_HOME": str(JAVA.parents[1]),
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


def bootstrap() -> None:
    """Load the agent, allowing launchd a moment to retire an older job."""
    result = launchctl("bootstrap", DOMAIN, str(PLIST_PATH), check=False)
    if result.returncode == 0 or is_loaded():
        return
    time.sleep(1)
    result = launchctl("bootstrap", DOMAIN, str(PLIST_PATH), check=False)
    if result.returncode != 0 and not is_loaded():
        raise subprocess.CalledProcessError(
            result.returncode,
            result.args,
            output=result.stdout,
            stderr=result.stderr,
        )


def require_runtime() -> None:
    if not JAVA.is_file():
        raise SystemExit(f"JDK 24 is missing: {JAVA}")
    if not JAR.is_file():
        raise SystemExit(f"Cloudflare-Faker has not been built: {JAR}")


def write_plist() -> None:
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{LABEL}.", suffix=".plist", dir=PLIST_PATH.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as output:
            plistlib.dump(service_configuration(), output, sort_keys=False)
        os.chmod(temporary_name, 0o644)
        os.replace(temporary_name, PLIST_PATH)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def install() -> None:
    require_runtime()
    if is_loaded():
        launchctl("bootout", SERVICE_TARGET, check=False)
        time.sleep(0.5)
    write_plist()
    launchctl("enable", SERVICE_TARGET)
    bootstrap()
    launchctl("kickstart", "-k", SERVICE_TARGET)
    print(f"classification=service_installed\nplist={PLIST_PATH}")


def start() -> None:
    require_runtime()
    if not PLIST_PATH.is_file():
        install()
        return
    launchctl("enable", SERVICE_TARGET)
    if not is_loaded():
        bootstrap()
    launchctl("kickstart", "-k", SERVICE_TARGET)
    print("classification=service_started")


def stop() -> None:
    if is_loaded():
        launchctl("bootout", SERVICE_TARGET)
    launchctl("disable", SERVICE_TARGET, check=False)
    print("classification=service_stopped")


def uninstall() -> None:
    stop()
    PLIST_PATH.unlink(missing_ok=True)
    print("classification=service_uninstalled")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("install", "start", "stop", "uninstall"))
    args = parser.parse_args()
    {"install": install, "start": start, "stop": stop, "uninstall": uninstall}[
        args.action
    ]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
