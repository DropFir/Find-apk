#!/usr/bin/env python3
"""Resolve one exact public download page and immediately save its package."""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
from pathlib import Path
import socket
import subprocess
import sys
from urllib.error import URLError
from urllib.parse import parse_qs, unquote, urljoin, urlparse, urlunparse

from extract_download_link import (
    VERSION_POLICIES,
    Analysis,
    PageResult,
    analyze_html,
    fetch_page,
)


TOOLS_DIR = Path(__file__).resolve().parent
DOWNLOAD_TOOL = TOOLS_DIR / "download_file.py"
PACKAGE_SUFFIXES = {".apk", ".xapk", ".apkm", ".apks"}
LARGE_PACKAGE_TIMEOUT = 60.0


class APKMirrorLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attributes = {key.lower(): value or "" for key, value in attrs}
        href = attributes.get("href", "").strip()
        if href:
            self.links.append(href)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resolve an exact package page and immediately download its file."
    )
    parser.add_argument("page_url", help="Exact public package download page URL")
    parser.add_argument("output", type=Path, help="Destination APK/XAPK/APKM/APKS")
    parser.add_argument("--package-name", required=True)
    parser.add_argument("--version", required=True, help="Reference or requested version")
    parser.add_argument(
        "--version-policy",
        choices=VERSION_POLICIES,
        default="prefer-latest",
        help="Prefer the newest available package; use exact only for a user-requested version",
    )
    parser.add_argument("--page-timeout", type=float, default=20.0)
    parser.add_argument("--download-timeout", type=float, default=20.0)
    parser.add_argument("--retries", type=int, choices=(0, 1), default=1)
    return parser.parse_args()


def validate_timeout(value: float, name: str) -> None:
    if value <= 0 or value > 60:
        raise SystemExit(f"{name} must be greater than 0 and no more than 60")


def apkpure_download_page_url(
    page_url: str, expected_package: str
) -> str | None:
    """Return APKPure's deterministic /download transition for an exact detail page."""
    parsed = urlparse(page_url)
    hostname = (parsed.hostname or "").casefold()
    if not (
        hostname in {"apkpure.com", "apkpure.net"}
        or hostname.endswith((".apkpure.com", ".apkpure.net"))
    ):
        return None
    path = parsed.path.rstrip("/")
    if path.casefold().endswith("/download"):
        return None
    if expected_package.casefold() not in unquote(path).casefold():
        return None
    return urlunparse(parsed._replace(path=f"{path}/download", query="", fragment=""))


def is_apkmirror_url(url: str) -> bool:
    hostname = (urlparse(url).hostname or "").casefold()
    return hostname == "apkmirror.com" or hostname.endswith(".apkmirror.com")


def parse_page_links(body: str, page_url: str) -> list[str]:
    parser = APKMirrorLinkParser()
    parser.feed(body)
    return list(dict.fromkeys(urljoin(page_url, href) for href in parser.links))


def apkmirror_intermediate_page_url(body: str, page_url: str) -> str | None:
    if not is_apkmirror_url(page_url):
        return None
    current_path = urlparse(page_url).path.rstrip("/")
    for link in parse_page_links(body, page_url):
        parsed = urlparse(link)
        query = parse_qs(parsed.query)
        if (
            is_apkmirror_url(link)
            and parsed.path.rstrip("/") == f"{current_path}/download"
            and query.get("key")
        ):
            return link
    return None


def apkmirror_final_download_url(body: str, page_url: str) -> str | None:
    if not is_apkmirror_url(page_url):
        return None
    for link in parse_page_links(body, page_url):
        parsed = urlparse(link)
        query = parse_qs(parsed.query)
        if (
            is_apkmirror_url(link)
            and parsed.path.casefold()
            == "/wp-content/themes/apkmirror/download.php"
            and query.get("id")
            and query.get("key")
        ):
            return link
    return None


def preserve_detected_version(
    analysis: Analysis, detected_version: str | None
) -> Analysis:
    """Keep the detail-page version when a transition page omits metadata."""
    if analysis.detected_version is None and detected_version is not None:
        analysis.detected_version = detected_version
    return analysis


def resolve_download_page(
    page_url: str,
    expected_package: str,
    expected_version: str,
    timeout: float,
    version_policy: str = "prefer-latest",
) -> tuple[PageResult, Analysis, str | None]:
    """Resolve one page, including APKPure's public detail-to-download transition."""
    page = fetch_page(page_url, timeout)
    analysis = analyze_html(
        page.body,
        page.final_url,
        status=page.status,
        expected_package=expected_package,
        expected_version=expected_version,
        version_policy=version_policy,
    )
    detected_version = analysis.detected_version
    transition_url = None
    if analysis.classification == "browser_required":
        transition_url = apkpure_download_page_url(page.final_url, expected_package)
        if transition_url is not None:
            page = fetch_page(transition_url, timeout)
            analysis = preserve_detected_version(
                analyze_html(
                    page.body,
                    page.final_url,
                    status=page.status,
                    expected_package=expected_package,
                    expected_version=expected_version,
                    version_policy=version_policy,
                ),
                detected_version,
            )
    if analysis.classification == "no_download_link" and is_apkmirror_url(
        page.final_url
    ):
        intermediate_url = apkmirror_intermediate_page_url(page.body, page.final_url)
        if intermediate_url is not None:
            transition_url = intermediate_url
            page = fetch_page(intermediate_url, timeout)
            analysis = preserve_detected_version(
                analyze_html(
                    page.body,
                    page.final_url,
                    status=page.status,
                    expected_package=expected_package,
                    expected_version=expected_version,
                    version_policy=version_policy,
                ),
                detected_version,
            )
            final_url = apkmirror_final_download_url(page.body, page.final_url)
            if final_url is not None and analysis.classification == "no_download_link":
                analysis = Analysis("download_link", [final_url], False)
    return page, analysis, transition_url


def main() -> int:
    args = parse_args()
    validate_timeout(args.page_timeout, "--page-timeout")
    validate_timeout(args.download_timeout, "--download-timeout")

    try:
        page, analysis, transition_url = resolve_download_page(
            args.page_url,
            args.package_name,
            args.version,
            args.page_timeout,
            args.version_policy,
        )
    except (URLError, socket.timeout, TimeoutError, ConnectionError, OSError, ValueError) as error:
        print("classification=network_error")
        print(f"error={type(error).__name__}: {error}")
        print("pipeline_result=page_fetch_failed")
        return 1

    if transition_url is not None:
        transition = (
            "apkmirror_download_page"
            if is_apkmirror_url(transition_url)
            else "apkpure_download_page"
        )
        print(f"transition={transition}")
        print(f"transition_page_url={transition_url}")
    print(f"classification={analysis.classification}")
    print(f"status={page.status}")
    print(f"page_url={page.final_url}")
    print(f"visible_captcha={str(analysis.visible_captcha).lower()}")
    if analysis.detected_version is not None:
        print(f"detected_version={analysis.detected_version}")
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
        timeout=(
            (
                max(args.download_timeout, LARGE_PACKAGE_TIMEOUT)
                if args.output.suffix.lower() in PACKAGE_SUFFIXES
                else args.download_timeout
            )
            + 3
        )
        * (args.retries + 1)
        + 5,
    )
    if completed.returncode == 0:
        print("pipeline_result=saved")
    else:
        print("pipeline_result=download_failed")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
