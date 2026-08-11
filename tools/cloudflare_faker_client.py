#!/usr/bin/env python3
"""Read one public page through the local Cloudflare-Faker Chrome extension."""

from __future__ import annotations

import argparse
import json
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid
from urllib.error import HTTPError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen


FAKER_API_URL = "http://127.0.0.1:8080/api/remote-html"
FAKER_DOWNLOAD_API_URL = "http://127.0.0.1:8080/api/remote-download"
FAKER_LOCK_PATH = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "vendor"
    / "runtime"
    / "cloudflare-faker.request.lock"
)
CHALLENGE_HTML_MARKERS = (
    "cf-browser-verification",
    "cf-chl-",
    "challenge-platform",
    "checking your browser",
    "just a moment",
    "please wait",
    "请稍候",
    "请稍后",
    "稍等片刻",
    "正在验证您是否是真人",
)


class CloudflareFakerError(ConnectionError):
    """The local service or its Chrome extension could not render the page."""


_CLOSE_FAKER_TAB_APPLESCRIPT = r"""
on run argv
    set markerText to item 1 of argv
    tell application "Google Chrome"
        repeat with chromeWindow in every window
            repeat with tabIndex from (count of tabs of chromeWindow) to 1 by -1
                set tabUrl to URL of tab tabIndex of chromeWindow
                if tabUrl contains markerText then
                    close tab tabIndex of chromeWindow
                end if
            end repeat
        end repeat
    end tell
end run
"""


def close_faker_tab(marker: str) -> bool:
    """Best-effort cleanup for the exact Chrome tab created by this request."""
    if sys.platform != "darwin" or not marker.startswith("_findapk_faker="):
        return False
    osascript = shutil.which("osascript")
    if not osascript:
        return False
    try:
        result = subprocess.run(
            [osascript, "-e", _CLOSE_FAKER_TAB_APPLESCRIPT, marker],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


class _FakerRequestLock:
    """Serialize access to the single Chrome extension across queue processes."""

    def __init__(self, timeout: float) -> None:
        self.timeout = timeout
        self.handle = None
        self.deadline = time.monotonic() + timeout

    def __enter__(self) -> float:
        FAKER_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.handle = FAKER_LOCK_PATH.open("a+")
        while True:
            try:
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                remaining = self.deadline - time.monotonic()
                if remaining <= 0:
                    fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
                    self.handle.close()
                    self.handle = None
                    raise CloudflareFakerError(
                        "Cloudflare-Faker request queue timed out"
                    )
                return remaining
            except BlockingIOError:
                if time.monotonic() >= self.deadline:
                    self.handle.close()
                    self.handle = None
                    raise CloudflareFakerError(
                        "Cloudflare-Faker request queue timed out"
                    )
                time.sleep(0.1)

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self.handle is not None:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()


def _request_rendered_html(page_url: str, timeout: float) -> str:
    request = Request(
        FAKER_API_URL,
        data=json.dumps(
            {
                "pageUrl": page_url,
                "script": "",
                "type": "LOAD_HTML",
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as error:
        raw = error.read()
        if not raw:
            raise CloudflareFakerError(
                f"Cloudflare-Faker HTTP {error.code}: {error.reason}"
            ) from error
    except OSError as error:
        raise CloudflareFakerError(str(error)) from error

    try:
        envelope = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CloudflareFakerError(
            "Cloudflare-Faker returned invalid JSON"
        ) from error

    if isinstance(envelope, dict) and envelope.get("error"):
        error = envelope["error"]
        if isinstance(error, dict):
            detail = error.get("message") or error.get("type") or str(error)
        else:
            detail = str(error)
        raise CloudflareFakerError(detail)

    data = envelope.get("data") if isinstance(envelope, dict) else None
    html = data.get("html") if isinstance(data, dict) else None
    if not isinstance(html, str) or not html.strip():
        raise CloudflareFakerError("Cloudflare-Faker returned no rendered HTML")
    return html


def is_cloudflare_challenge_html(html: str) -> bool:
    lowered = html.casefold()
    return any(marker in lowered for marker in CHALLENGE_HTML_MARKERS)


def download_package_with_browser(
    page_url: str,
    download_url: str,
    timeout: float = 900.0,
) -> tuple[Path, str, int]:
    """Click an exact package link and wait for Chrome's native download."""
    page = urlparse(page_url)
    package = urlparse(download_url)
    if page.scheme not in {"http", "https"} or not page.hostname:
        raise ValueError("Cloudflare-Faker page URL must use HTTP(S)")
    if package.scheme not in {"http", "https"} or not package.hostname:
        raise ValueError("Cloudflare-Faker download URL must use HTTP(S)")
    if timeout <= 0 or timeout > 900:
        raise ValueError(
            "Cloudflare-Faker download timeout must be greater than 0 and no more than 900"
        )

    # Keep the exact page URL for native package downloads. This allows the
    # extension to reuse a page the user has already opened and passed through
    # Cloudflare, instead of forcing a fresh marked tab that may be challenged.
    # Tabs created by the extension are tracked and closed by its own task
    # cleanup; an existing user tab is intentionally left open.
    navigation_url = page_url
    normalized_path = page.path.rstrip("/")
    if normalized_path.endswith("/download"):
        entry_path = normalized_path[: -len("/download")] or "/"
        entry_page_url = urlunparse(
            page._replace(path=entry_path, query="", fragment="")
        )
    else:
        entry_page_url = page_url
    request_timeout = timeout + 60.0

    with _FakerRequestLock(request_timeout):
        request = Request(
            FAKER_DOWNLOAD_API_URL,
            data=json.dumps(
                {
                    "pageUrl": navigation_url,
                    "entryPageUrl": entry_page_url,
                    "script": download_url,
                    "type": "DOWNLOAD_PACKAGE",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=request_timeout) as response:
                raw = response.read()
        except HTTPError as error:
            raw = error.read()
            if not raw:
                raise CloudflareFakerError(
                    f"Cloudflare-Faker HTTP {error.code}: {error.reason}"
                ) from error
        except OSError as error:
            raise CloudflareFakerError(str(error)) from error

    try:
        envelope = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CloudflareFakerError(
            "Cloudflare-Faker returned invalid download JSON"
        ) from error
    if isinstance(envelope, dict) and envelope.get("error"):
        error = envelope["error"]
        if isinstance(error, dict):
            detail = error.get("message") or error.get("type") or str(error)
        else:
            detail = str(error)
        raise CloudflareFakerError(detail)
    data = envelope.get("data") if isinstance(envelope, dict) else None
    path = data.get("path") if isinstance(data, dict) else None
    final_url = data.get("url", "") if isinstance(data, dict) else ""
    byte_count = data.get("bytes", 0) if isinstance(data, dict) else 0
    if not isinstance(path, str) or not path.strip():
        raise CloudflareFakerError(
            "Cloudflare-Faker returned no completed download path"
        )
    downloaded = Path(path).expanduser().resolve(strict=False)
    if not downloaded.is_file():
        raise CloudflareFakerError(
            "Cloudflare-Faker completed download file is missing"
        )
    return (
        downloaded,
        final_url if isinstance(final_url, str) else "",
        int(byte_count) if isinstance(byte_count, (int, float)) else 0,
    )


def fetch_rendered_html(page_url: str, timeout: float = 45.0) -> str:
    parsed = urlparse(page_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Cloudflare-Faker page URL must use HTTP(S)")
    if timeout <= 0 or timeout > 60:
        raise ValueError(
            "Cloudflare-Faker timeout must be greater than 0 and no more than 60"
        )

    # Cloudflare-Faker reuses a matching Chrome tab without reloading it.  A
    # previous failed navigation can therefore leave an "Error" tab that has no
    # content script, making every later command wait until timeout.  A unique
    # fragment forces a fresh tab while leaving the HTTP request unchanged.
    marker = f"_findapk_faker={uuid.uuid4().hex}"
    fragment = f"{parsed.fragment}&{marker}" if parsed.fragment else marker
    navigation_url = urlunparse(parsed._replace(fragment=fragment))

    deadline = time.monotonic() + timeout
    with _FakerRequestLock(timeout):
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CloudflareFakerError(
                        "Cloudflare-Faker page remained on the challenge screen"
                    )
                html = _request_rendered_html(navigation_url, remaining)
                if not is_cloudflare_challenge_html(html):
                    return html
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CloudflareFakerError(
                        "Cloudflare-Faker page remained on the challenge screen"
                    )
                # Reuse the same marked tab so Cloudflare can finish its
                # browser-side verification and keep the resulting session.
                time.sleep(min(1.0, remaining))
        finally:
            # The extension intentionally creates a fresh tab for the unique
            # marker. Close only that exact work tab, whether the request
            # succeeds, fails, or times out, before allowing another request.
            close_faker_tab(marker)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--timeout", type=float, default=45.0)
    args = parser.parse_args()
    if not args.check:
        parser.error("--check is required")
    health_url = f"http://127.0.0.1:8080/#findapk-health-{os.getpid()}"
    try:
        html = fetch_rendered_html(health_url, args.timeout)
    except (CloudflareFakerError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    if "Cloudflare-Faker Dashboard" not in html:
        print("Cloudflare-Faker health page was not rendered", file=sys.stderr)
        return 1
    print("Cloudflare-Faker Chrome extension is connected and executable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
