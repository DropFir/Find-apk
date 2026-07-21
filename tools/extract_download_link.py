#!/usr/bin/env python3
"""Extract a public package link without mistaking passive CAPTCHA assets for a prompt."""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Upgrade-Insecure-Requests": "1",
}
MAX_HTML_BYTES = 2 * 1024 * 1024
CHALLENGE_MARKERS = (
    "cf-browser-verification",
    "cf-chl-",
    "checking your browser",
    "just a moment",
)
VISIBLE_CAPTCHA_TEXT = (
    "complete the captcha",
    "solve the captcha",
    "enter the captcha",
    "verify you are human",
    "human verification required",
)
CAPTCHA_CLASSES = {"g-recaptcha", "h-captcha", "cf-turnstile"}
APKCOMBO_BROWSER_REQUIRED_MARKERS = (
    "downloading. just a sec",
    "sorry, something went wrong",
)
APKPURE_DOWNLOAD_HOSTS = {
    "d.apkpure.com",
    "d.apkpure.net",
    "download.apkpure.com",
    "download.pureapk.com",
}


@dataclass
class PageResult:
    status: int
    final_url: str
    content_type: str
    body: str


@dataclass
class Analysis:
    classification: str
    links: list[str]
    visible_captcha: bool


class DownloadPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.visible_captcha = False
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value or "" for key, value in attrs}
        if tag in {"script", "style", "noscript"}:
            self._ignored_depth += 1

        class_names = set(attributes.get("class", "").lower().split())
        if class_names.intersection(CAPTCHA_CLASSES):
            self.visible_captcha = True

        source = attributes.get("src", "").lower()
        if tag == "iframe" and any(
            marker in source
            for marker in ("recaptcha", "hcaptcha", "turnstile", "challenges.cloudflare.com")
        ):
            self.visible_captcha = True

        href = attributes.get("href", "")
        is_variant = "variant" in class_names
        is_signed_redirect = href.startswith(("/r2?u=", "/d?u="))
        download_host = (urlparse(href).hostname or "").lower()
        is_apkpure_download = download_host in APKPURE_DOWNLOAD_HOSTS
        if tag == "a" and href and (
            is_variant or is_signed_redirect or is_apkpure_download
        ):
            self.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        normalized = " ".join(data.lower().split())
        if any(marker in normalized for marker in VISIBLE_CAPTCHA_TEXT):
            self.visible_captcha = True


def analyze_html(
    body: str,
    page_url: str,
    status: int = 200,
    expected_package: str | None = None,
    expected_version: str | None = None,
) -> Analysis:
    lowered = body.lower()
    parsed_page_url = urlparse(page_url)
    hostname = (parsed_page_url.hostname or "").lower()
    is_apkpure_exact_page = (
        (
            hostname in {"apkpure.com", "apkpure.net"}
            or hostname.endswith((".apkpure.com", ".apkpure.net"))
        )
        and expected_package is not None
    )
    is_uptodown_exact_page = (
        (hostname == "uptodown.com" or hostname.endswith(".uptodown.com"))
        and parsed_page_url.path.rstrip("/").endswith(("/android", "/android/download"))
        and expected_package is not None
    )
    if status in (401, 403) and any(marker in lowered for marker in CHALLENGE_MARKERS):
        return Analysis("cloudflare_challenge", [], False)
    if status == 410:
        return Analysis("gone", [], False)
    if status == 404:
        # Uptodown serves a 404 to some non-browser clients while the same
        # exact public app/download page is available in a real browser.
        # Treat this as a required browser render, not evidence of deletion.
        if is_uptodown_exact_page:
            return Analysis("browser_required", [], False)
        return Analysis("not_found", [], False)
    if status == 429:
        return Analysis("rate_limited", [], False)
    if status >= 500:
        return Analysis("server_error", [], False)
    if status >= 400:
        return Analysis("http_error", [], False)

    if expected_package and expected_package.lower() not in lowered:
        return Analysis("package_mismatch", [], False)
    if expected_version and expected_version.lower() not in lowered:
        return Analysis("version_mismatch", [], False)

    parser = DownloadPageParser()
    parser.feed(body)
    links = list(dict.fromkeys(urljoin(page_url, link) for link in parser.links))
    if links:
        return Analysis("download_link", links, parser.visible_captcha)
    if parser.visible_captcha:
        return Analysis("captcha_required", [], True)
    if (
        (hostname == "apkcombo.com" or hostname.endswith(".apkcombo.com"))
        and all(marker in lowered for marker in APKCOMBO_BROWSER_REQUIRED_MARKERS)
    ):
        # APKCombo sometimes returns a server-rendered loading/error shell to
        # HTTP clients while a real browser session receives the signed
        # ``variant`` anchor.  Calling this "no_download_link" is a false
        # negative and prevents the required browser fallback.
        return Analysis("browser_required", [], False)
    if is_uptodown_exact_page:
        return Analysis("browser_required", [], False)
    if is_apkpure_exact_page:
        # APKPure detail pages often expose only a browser-rendered
        # "Download APK/XAPK" transition to the package's /download page.
        # The absence of a file-host anchor on the detail page is therefore
        # not evidence that the package has no public download.
        return Analysis("browser_required", [], False)
    return Analysis("no_download_link", [], False)


def fetch_with_urllib(url: str, timeout: float) -> PageResult:
    request = Request(url, headers=BROWSER_HEADERS, method="GET")
    response = None
    try:
        response = urlopen(request, timeout=timeout)
    except HTTPError as error:
        response = error
    try:
        raw = response.read(MAX_HTML_BYTES + 1)
        if len(raw) > MAX_HTML_BYTES:
            raise ValueError("download page exceeds the 2 MiB inspection limit")
        charset = response.headers.get_content_charset() or "utf-8"
        return PageResult(
            status=int(getattr(response, "status", response.getcode())),
            final_url=response.geturl(),
            content_type=response.headers.get("Content-Type", ""),
            body=raw.decode(charset, errors="replace"),
        )
    finally:
        response.close()


def fetch_with_curl(url: str, timeout: float) -> PageResult:
    curl = shutil.which("curl")
    if curl is None:
        raise OSError("curl is unavailable for the fallback page request")
    marker = "__FIND_APK_PAGE_META__"
    command = [
        curl,
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
        f"Accept: {BROWSER_HEADERS['Accept']}",
        "--header",
        f"Accept-Language: {BROWSER_HEADERS['Accept-Language']}",
        "--write-out",
        f"\n{marker}%{{http_code}}\t%{{content_type}}\t%{{url_effective}}",
        url,
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        timeout=timeout + 2,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode(errors="replace").strip()
        raise ConnectionError(detail or f"curl exit code {completed.returncode}")
    body_bytes, separator, metadata = completed.stdout.rpartition(
        ("\n" + marker).encode()
    )
    if not separator:
        raise OSError("curl did not return page metadata")
    fields = metadata.decode(errors="replace").split("\t", 2)
    if len(fields) != 3:
        raise OSError("curl returned invalid page metadata")
    status_text, content_type, final_url = fields
    if len(body_bytes) > MAX_HTML_BYTES:
        raise ValueError("download page exceeds the 2 MiB inspection limit")
    return PageResult(
        status=int(status_text),
        final_url=final_url,
        content_type=content_type,
        body=body_bytes.decode("utf-8", errors="replace"),
    )


def fetch_page(url: str, timeout: float) -> PageResult:
    deadline = time.monotonic() + timeout
    try:
        return fetch_with_urllib(url, timeout)
    except (URLError, socket.timeout, TimeoutError, ConnectionError, OSError):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise
        return fetch_with_curl(url, remaining)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract the current package link from a public download page."
    )
    parser.add_argument("url", help="Exact public download page URL")
    parser.add_argument("--package-name", help="Expected Android package name")
    parser.add_argument("--version", help="Expected version string")
    parser.add_argument("--timeout", type=float, default=20.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.timeout <= 0 or args.timeout > 60:
        raise SystemExit("--timeout must be greater than 0 and no more than 60")
    try:
        page = fetch_page(args.url, args.timeout)
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
        return 1

    print(f"classification={analysis.classification}")
    print(f"status={page.status}")
    print(f"page_url={page.final_url}")
    print(f"visible_captcha={str(analysis.visible_captcha).lower()}")
    print(f"candidate_count={len(analysis.links)}")
    if analysis.links:
        print(f"download_url={analysis.links[0]}")
    return 0 if analysis.classification == "download_link" else 1


if __name__ == "__main__":
    raise SystemExit(main())
