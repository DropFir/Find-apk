#!/usr/bin/env python3
"""Probe a public app or download page with browser-navigation headers."""

from __future__ import annotations

import argparse
import html
import re
import socket
import sys
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cache-Control": "max-age=0",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

MAX_INSPECT_BYTES = 64 * 1024
CHALLENGE_MARKERS = (
    "just a moment",
    "checking your browser",
    "verify you are human",
    "cf-browser-verification",
    "challenges.cloudflare.com",
)


@dataclass
class ProbeResult:
    status: int
    final_url: str
    content_type: str
    content_length: str
    server: str
    cf_mitigated: str
    title: str
    classification: str


def classify(status: int, cf_mitigated: str, body: str) -> str:
    """Classify the response without claiming that HTTP 200 is a file."""
    lowered = body.lower()
    if cf_mitigated.lower() == "challenge":
        return "cloudflare_challenge"
    if status == 410:
        return "gone"
    if status == 404:
        return "not_found"
    if status == 429:
        return "rate_limited"
    if status >= 500:
        return "server_error"
    if status in (401, 403) or any(marker in lowered for marker in CHALLENGE_MARKERS):
        return "cloudflare_challenge" if "cloudflare" in lowered else "http_error"
    if 200 <= status < 400:
        return "ok"
    return "http_error"


def extract_title(body: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    title = re.sub(r"\s+", " ", html.unescape(match.group(1))).strip()
    return title[:200]


def probe(url: str, timeout: float) -> ProbeResult:
    request = Request(url, headers=BROWSER_HEADERS, method="GET")
    response = None
    try:
        response = urlopen(request, timeout=timeout)
    except HTTPError as error:
        response = error

    try:
        status = int(getattr(response, "status", response.getcode()))
        headers = response.headers
        raw = response.read(MAX_INSPECT_BYTES)
        charset = headers.get_content_charset() or "utf-8"
        body = raw.decode(charset, errors="replace")
        cf_mitigated = headers.get("Cf-Mitigated", "")
        return ProbeResult(
            status=status,
            final_url=response.geturl(),
            content_type=headers.get("Content-Type", ""),
            content_length=headers.get("Content-Length", ""),
            server=headers.get("Server", ""),
            cf_mitigated=cf_mitigated,
            title=extract_title(body),
            classification=classify(status, cf_mitigated, body),
        )
    finally:
        response.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe a public URL and distinguish Cloudflare from missing resources."
    )
    parser.add_argument("url", help="Public app page or download URL")
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Request timeout in seconds (default: 20)",
    )
    args = parser.parse_args()

    if args.timeout <= 0 or args.timeout > 60:
        parser.error("--timeout must be greater than 0 and no more than 60")

    try:
        result = probe(args.url, args.timeout)
    except (URLError, socket.timeout, TimeoutError, ValueError) as error:
        print("classification=network_error")
        print(f"error={type(error).__name__}: {error}")
        return 1

    print(f"classification={result.classification}")
    print(f"status={result.status}")
    print(f"final_url={result.final_url}")
    print(f"content_type={result.content_type}")
    print(f"content_length={result.content_length}")
    print(f"server={result.server}")
    print(f"cf_mitigated={result.cf_mitigated}")
    print(f"title={result.title}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
