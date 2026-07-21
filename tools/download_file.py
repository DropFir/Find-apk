#!/usr/bin/env python3
"""Download one public asset atomically and reject HTML masquerading as a file."""

from __future__ import annotations

import argparse
from http.client import HTTPException, IncompleteRead
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
PACKAGE_SUFFIXES = {".apk", ".xapk", ".apkm", ".apks"}
ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
CHUNK_SIZE = 1024 * 1024
INSPECT_SIZE = 512


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download a public APK or image with one bounded retry."
    )
    parser.add_argument("url", help="Direct public file URL")
    parser.add_argument("output", type=Path, help="Destination file path")
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Socket timeout in seconds (default: 20)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        choices=(0, 1),
        default=1,
        help="Number of retries after a network or server error (default: 1)",
    )
    return parser.parse_args()


def validate_download(path: Path, suffix: str, content_type: str) -> None:
    with path.open("rb") as downloaded:
        prefix = downloaded.read(INSPECT_SIZE)

    lowered = prefix.lstrip().lower()
    normalized_type = content_type.partition(";")[0].strip().lower()
    if normalized_type in {"text/html", "application/xhtml+xml"} or lowered.startswith(
        (b"<!doctype html", b"<html", b"<head", b"<body")
    ):
        raise ValueError("server returned HTML instead of the requested file")

    if suffix in PACKAGE_SUFFIXES and not prefix.startswith(ZIP_SIGNATURES):
        raise ValueError("download is not a ZIP-based Android package")
    if suffix == ".webp" and not (
        prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP"
    ):
        raise ValueError("download is not a WEBP image")
    if not prefix:
        raise ValueError("downloaded file is empty")


def set_read_timeout(response: object, timeout: float) -> None:
    """Apply the remaining deadline to urllib's underlying socket when available."""
    for path in (
        ("fp", "fp", "raw", "_sock"),
        ("fp", "raw", "_sock"),
        ("raw", "_sock"),
        ("_sock",),
    ):
        current = response
        for attribute in path:
            current = getattr(current, attribute, None)
            if current is None:
                break
        settimeout = getattr(current, "settimeout", None)
        if settimeout is not None:
            settimeout(max(timeout, 0.001))
            return


def download_once(url: str, temporary: Path, timeout: float) -> tuple[str, str, int]:
    deadline = time.monotonic() + timeout
    request = Request(url, headers=BROWSER_HEADERS, method="GET")
    with urlopen(request, timeout=timeout) as response, temporary.open("wb") as output:
        content_type = response.headers.get("Content-Type", "")
        content_length = response.headers.get("Content-Length", "")
        expected_length = int(content_length) if content_length.isdigit() else None
        total = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"download exceeded {timeout:g} seconds")
            set_read_timeout(response, remaining)
            chunk = response.read(CHUNK_SIZE)
            if not chunk:
                break
            output.write(chunk)
            total += len(chunk)
        if expected_length is not None and total != expected_length:
            raise IncompleteRead(b"", expected_length - total)
        return response.geturl(), content_type, total


def download_with_curl(
    url: str, temporary: Path, timeout: float
) -> tuple[str, str, int]:
    curl = shutil.which("curl")
    if curl is None:
        raise OSError("curl is unavailable for the fallback download attempt")

    marker = "__FIND_APK_CURL_META__"
    command = [
        curl,
        # Some APK CDNs close macOS curl's negotiated HTTP/2 connection even
        # though the same HTTPS URL works over IPv4 + HTTP/1.1.  Keep the
        # fallback secure while avoiding an unnecessary browser handoff or
        # plaintext HTTP downgrade.
        "--ipv4",
        "--http1.1",
        "--location",
        "--silent",
        "--show-error",
        "--connect-timeout",
        f"{timeout:g}",
        "--max-time",
        f"{timeout:g}",
        "--user-agent",
        BROWSER_HEADERS["User-Agent"],
        "--header",
        f"Accept-Language: {BROWSER_HEADERS['Accept-Language']}",
    ]
    if temporary.exists() and temporary.stat().st_size > 0:
        command.extend(["--continue-at", "-"])
    command.extend(
        [
            "--output",
            str(temporary),
            "--write-out",
            f"{marker}%{{http_code}}\t%{{content_type}}\t%{{url_effective}}",
            url,
        ]
    )
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout + 2,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"curl exit code {completed.returncode}"
        raise ConnectionError(detail)

    metadata = completed.stdout.rpartition(marker)[2]
    fields = metadata.split("\t", 2)
    if len(fields) != 3:
        raise OSError("curl did not return download metadata")
    status_text, content_type, final_url = fields
    status = int(status_text)
    if status == 429 or status >= 500:
        raise ConnectionError(f"HTTP {status}")
    if status >= 400:
        raise ValueError(f"HTTP {status}")
    return final_url, content_type, temporary.stat().st_size


def should_retry(error: BaseException) -> bool:
    if isinstance(error, HTTPError):
        return error.code == 429 or error.code >= 500
    return isinstance(
        error,
        (URLError, HTTPException, socket.timeout, TimeoutError, ConnectionError),
    )


def main() -> int:
    args = parse_args()
    if args.timeout <= 0 or args.timeout > 60:
        raise SystemExit("--timeout must be greater than 0 and no more than 60")

    output = args.output.expanduser().resolve(strict=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.parent / f".{output.name}.{uuid.uuid4().hex}.part"
    attempts = args.retries + 1

    try:
        temporary.unlink(missing_ok=True)
        for attempt in range(1, attempts + 1):
            try:
                if attempt > 1 and shutil.which("curl") is not None:
                    final_url, content_type, total = download_with_curl(
                        args.url, temporary, args.timeout
                    )
                else:
                    final_url, content_type, total = download_once(
                        args.url, temporary, args.timeout
                    )
                validate_download(temporary, output.suffix.lower(), content_type)
                os.replace(temporary, output)
                print(f"output={output.as_posix()}")
                print(f"bytes={total}")
                print(f"content_type={content_type}")
                print(f"final_url={final_url}")
                return 0
            except (
                HTTPError,
                URLError,
                HTTPException,
                socket.timeout,
                TimeoutError,
                ConnectionError,
                subprocess.TimeoutExpired,
                OSError,
                ValueError,
            ) as error:
                if attempt >= attempts or not should_retry(error):
                    print(f"Download failed: {error}", file=sys.stderr)
                    return 1
        return 1
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
