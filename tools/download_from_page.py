#!/usr/bin/env python3
"""Resolve one exact public download page and immediately save its package."""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
from pathlib import Path
import re
import socket
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

from cloudflare_faker_client import CloudflareFakerError, fetch_rendered_html
from extract_download_link import (
    VERSION_POLICIES,
    Analysis,
    PageResult,
    analyze_html,
    fetch_page,
)
from http_headers import BROWSER_NAVIGATION_HEADERS


TOOLS_DIR = Path(__file__).resolve().parent
DOWNLOAD_TOOL = TOOLS_DIR / "download_file.py"
PACKAGE_SUFFIXES = {".apk", ".xapk", ".apkm", ".apks"}
LARGE_PACKAGE_TIMEOUT = 900.0
APKPURE_CDN_BASE = "https://d.apkpure.com/b"
APKPURE_CDN_CONTENT_TYPES = {
    "APK": {
        "application/vnd.android.package-archive",
        "application/octet-stream",
        "application/zip",
    },
    "XAPK": {
        "application/xapk-package-archive",
        "application/octet-stream",
        "application/zip",
    },
}
APKPURE_CDN_HEADERS = {
    "User-Agent": BROWSER_NAVIGATION_HEADERS["User-Agent"],
    "Accept": "*/*",
    "Accept-Language": BROWSER_NAVIGATION_HEADERS["Accept-Language"],
}


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
    parser.add_argument(
        "--cloudflare-faker",
        action="store_true",
        help="Render a confirmed Cloudflare/browser-blocked page through local Chrome",
    )
    parser.add_argument(
        "--faker-timeout",
        type=float,
        default=45.0,
        help="Cloudflare-Faker render timeout; independent from the normal page timeout",
    )
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


def is_apkpure_cdn_url(url: str) -> bool:
    hostname = (urlparse(url).hostname or "").casefold()
    return hostname in {"d.apkpure.com", "d.apkpure.net"}


def apkpure_cdn_candidate_urls(
    expected_package: str, preferred_suffix: str | None = None
) -> list[tuple[str, str]]:
    """Return stable APKPure CDN endpoints in the requested package format."""
    normalized_suffix = (preferred_suffix or "").casefold()
    if normalized_suffix == ".apk":
        formats = ("APK",)
    elif normalized_suffix == ".xapk":
        formats = ("XAPK",)
    elif normalized_suffix in {".apkm", ".apks"}:
        formats = ()
    else:
        formats = ("XAPK", "APK")
    package = quote(expected_package, safe=".")
    return [
        (package_format, f"{APKPURE_CDN_BASE}/{package_format}/{package}?version=latest")
        for package_format in formats
    ]


def probe_apkpure_cdn_download(
    expected_package: str,
    timeout: float,
    preferred_suffix: str | None = None,
) -> tuple[str, PageResult] | None:
    """HEAD stable APKPure endpoints and accept only a matching package archive."""
    for package_format, candidate_url in apkpure_cdn_candidate_urls(
        expected_package, preferred_suffix
    ):
        request = Request(candidate_url, headers=APKPURE_CDN_HEADERS, method="HEAD")
        try:
            with urlopen(request, timeout=timeout) as response:
                status = int(getattr(response, "status", response.getcode()))
                final_url = response.geturl()
                content_type = response.headers.get("Content-Type", "")
                content_length = response.headers.get("Content-Length", "")
                disposition = unquote(
                    response.headers.get("Content-Disposition", "")
                ).casefold()
        except (HTTPError, URLError, socket.timeout, TimeoutError, OSError):
            continue

        normalized_type = content_type.partition(";")[0].strip().casefold()
        final_package = parse_qs(urlparse(final_url).query).get("package_name", [])
        package_matches = bool(final_package) and any(
            value.casefold() == expected_package.casefold() for value in final_package
        )
        filenames = parse_qs(urlparse(final_url).query).get("filename", [])
        final_filename = filenames[0].casefold() if filenames else disposition
        format_matches = (
            normalized_type in APKPURE_CDN_CONTENT_TYPES[package_format]
            and final_filename.rstrip('"').endswith(
                f".{package_format.casefold()}"
            )
        )
        if (
            status == 200
            and package_matches
            and format_matches
            and content_length.isdigit()
            and int(content_length) > 0
        ):
            return (
                candidate_url,
                PageResult(status, final_url, content_type, ""),
            )
    return None


def apkpure_cdn_detected_version(final_url: str) -> str | None:
    """Extract APKPure's actual latest version from the signed CDN filename."""
    filenames = parse_qs(urlparse(final_url).query).get("filename", [])
    if not filenames:
        return None
    match = re.search(
        r"_([0-9][0-9A-Za-z.+-]*)_APKPure\.(?:apk|xapk)$",
        filenames[0],
        re.IGNORECASE,
    )
    return match.group(1) if match else None


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
    preferred_suffix: str | None = None,
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
            if analysis.classification in {
                "browser_required",
                "cloudflare_challenge",
                "gone",
                "not_found",
                "no_download_link",
            }:
                cdn_result = probe_apkpure_cdn_download(
                    expected_package,
                    timeout,
                    preferred_suffix,
                )
                if cdn_result is not None:
                    cdn_url, page = cdn_result
                    transition_url = cdn_url
                    analysis = Analysis(
                        "download_link",
                        [cdn_url],
                        False,
                        apkpure_cdn_detected_version(page.final_url)
                        or detected_version,
                    )
    elif analysis.classification == "cloudflare_challenge":
        # An exact APKPure candidate may be intermittently challenged while
        # its public package CDN remains available.  The stable endpoint is
        # still verified by its redirected package_name, format, type, and
        # content length before it is accepted.
        exact_download_url = apkpure_download_page_url(
            page.final_url, expected_package
        )
        if exact_download_url is not None:
            cdn_result = probe_apkpure_cdn_download(
                expected_package,
                timeout,
                preferred_suffix,
            )
            if cdn_result is not None:
                cdn_url, page = cdn_result
                transition_url = cdn_url
                analysis = Analysis(
                    "download_link",
                    [cdn_url],
                    False,
                    apkpure_cdn_detected_version(page.final_url),
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
            # APKMirror's keyed intermediate page often omits the package name
            # even though the preceding exact variant page already established
            # it.  Do not discard its vetted download.php link solely for that
            # intermediate-page omission.
            if final_url is not None and analysis.classification in {
                "no_download_link",
                "package_mismatch",
            }:
                analysis = Analysis("download_link", [final_url], False)
    return page, analysis, transition_url


def main() -> int:
    args = parse_args()
    validate_timeout(args.page_timeout, "--page-timeout")
    validate_timeout(args.download_timeout, "--download-timeout")
    if args.faker_timeout <= 0 or args.faker_timeout > 45:
        raise SystemExit("--faker-timeout must be greater than 0 and no more than 45")

    try:
        page, analysis, transition_url = resolve_download_page(
            args.page_url,
            args.package_name,
            args.version,
            args.page_timeout,
            args.version_policy,
            args.output.suffix.lower(),
        )
        faker_used = False
        if args.cloudflare_faker and analysis.classification in {
            "browser_required",
            "cloudflare_challenge",
        }:
            faker_url = (
                transition_url
                or apkpure_download_page_url(page.final_url, args.package_name)
                or page.final_url
            )
            rendered_html = fetch_rendered_html(
                faker_url,
                args.faker_timeout,
            )
            detected_version = analysis.detected_version
            page = PageResult(200, faker_url, "text/html", rendered_html)
            analysis = preserve_detected_version(
                analyze_html(
                    page.body,
                    page.final_url,
                    status=page.status,
                    expected_package=args.package_name,
                    expected_version=args.version,
                    version_policy=args.version_policy,
                ),
                detected_version,
            )
            transition_url = faker_url
            faker_used = True
    except (
        CloudflareFakerError,
        URLError,
        socket.timeout,
        TimeoutError,
        ConnectionError,
        OSError,
        ValueError,
    ) as error:
        print("classification=network_error")
        print(f"error={type(error).__name__}: {error}")
        print("pipeline_result=page_fetch_failed")
        return 1

    if faker_used:
        print("transition=cloudflare_faker")
        print(f"transition_page_url={transition_url}")
    elif transition_url is not None:
        if is_apkmirror_url(transition_url):
            transition = "apkmirror_download_page"
        elif is_apkpure_cdn_url(transition_url):
            transition = "apkpure_cdn_fallback"
        else:
            transition = "apkpure_download_page"
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
