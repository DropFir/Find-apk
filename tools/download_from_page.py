#!/usr/bin/env python3
"""Resolve one exact public download page and immediately save its package."""

from __future__ import annotations

import argparse
from pathlib import Path
import socket
import subprocess
import sys
from urllib.error import URLError

from extract_download_link import analyze_html, fetch_page


TOOLS_DIR = Path(__file__).resolve().parent
DOWNLOAD_TOOL = TOOLS_DIR / "download_file.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resolve an exact package page and immediately download its file."
    )
    parser.add_argument("page_url", help="Exact public package download page URL")
    parser.add_argument("output", type=Path, help="Destination APK/XAPK/APKM/APKS")
    parser.add_argument("--package-name", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--page-timeout", type=float, default=20.0)
    parser.add_argument("--download-timeout", type=float, default=20.0)
    parser.add_argument("--retries", type=int, choices=(0, 1), default=1)
    return parser.parse_args()


def validate_timeout(value: float, name: str) -> None:
    if value <= 0 or value > 60:
        raise SystemExit(f"{name} must be greater than 0 and no more than 60")


def main() -> int:
    args = parse_args()
    validate_timeout(args.page_timeout, "--page-timeout")
    validate_timeout(args.download_timeout, "--download-timeout")

    try:
        page = fetch_page(args.page_url, args.page_timeout)
        analysis = analyze_html(
            page.body,
            page.final_url,
            status=page.status,
            expected_package=args.package_name,
            expected_version=args.version,
        )
    except (URLError, socket.timeout, TimeoutError, ConnectionError, OSError, ValueError) as error:
        print("classification=network_error")
        print(f"error={type(error).__name__}: {error}")
        print("pipeline_result=page_fetch_failed")
        return 1

    print(f"classification={analysis.classification}")
    print(f"status={page.status}")
    print(f"page_url={page.final_url}")
    print(f"visible_captcha={str(analysis.visible_captcha).lower()}")
    print(f"candidate_count={len(analysis.links)}")
    if not analysis.links:
        if analysis.classification == "browser_required":
            print("pipeline_result=browser_required")
        else:
            print(f"pipeline_result={analysis.classification}")
        return 1

    download_url = analysis.links[0]
    print(f"download_url={download_url}")
    sys.stdout.flush()
    command = [
        sys.executable,
        str(DOWNLOAD_TOOL),
        download_url,
        str(args.output),
        "--timeout",
        f"{args.download_timeout:g}",
        "--retries",
        str(args.retries),
    ]
    completed = subprocess.run(
        command,
        check=False,
        timeout=(args.download_timeout + 3) * (args.retries + 1) + 5,
    )
    if completed.returncode == 0:
        print("pipeline_result=saved")
    else:
        print("pipeline_result=download_failed")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
