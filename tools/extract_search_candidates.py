#!/usr/bin/env python3
"""Fetch one configured search page and extract exact package candidates."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from html.parser import HTMLParser
import socket
from urllib.error import URLError
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from extract_download_link import CHALLENGE_MARKERS, fetch_page


SKIP_PATH_PARTS = {
    "category",
    "download-management",
    "login",
    "search",
    "topic",
}


@dataclass
class SearchAnalysis:
    classification: str
    links: list[str]


class SearchPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a" or self._href is not None:
            return
        attributes = {key.lower(): value or "" for key, value in attrs}
        href = attributes.get("href", "").strip()
        if href:
            self._href = href
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            text = " ".join(" ".join(self._text).split())
            self.links.append((self._href, text))
            self._href = None
            self._text = []


def redirected_to_generic_search(original_url: str, final_url: str) -> bool:
    original = urlparse(original_url)
    final = urlparse(final_url)
    original_query = parse_qs(original.query).get("q", [])
    final_query = parse_qs(final.query).get("q", [])
    return bool(
        original_query
        and not final_query
        and final.path.rstrip("/").endswith("/search")
    )


def is_candidate_url(url: str, expected_package: str) -> bool:
    parsed = urlparse(url)
    decoded = unquote(url).casefold()
    path_parts = {part.casefold() for part in parsed.path.split("/") if part}
    if not parsed.hostname or path_parts.intersection(SKIP_PATH_PARTS):
        return False
    return expected_package.casefold() in decoded


def analyze_search_html(
    body: str,
    original_url: str,
    final_url: str,
    status: int,
    expected_package: str,
) -> SearchAnalysis:
    lowered = body.casefold()
    if any(marker in lowered for marker in CHALLENGE_MARKERS):
        return SearchAnalysis("cloudflare_challenge", [])
    if status == 410:
        return SearchAnalysis("gone", [])
    if status == 404:
        return SearchAnalysis("not_found", [])
    if status == 429:
        return SearchAnalysis("rate_limited", [])
    if status >= 500:
        return SearchAnalysis("server_error", [])
    if status >= 400:
        return SearchAnalysis("http_error", [])
    if redirected_to_generic_search(original_url, final_url):
        return SearchAnalysis("generic_search_redirect", [])

    parser = SearchPageParser()
    parser.feed(body)
    links: list[str] = []
    for href, text in parser.links:
        absolute = urljoin(final_url, href)
        if is_candidate_url(absolute, expected_package) or expected_package.casefold() in text.casefold():
            if is_candidate_url(absolute, expected_package) and absolute not in links:
                links.append(absolute)
    if links:
        return SearchAnalysis("candidate_found", links)
    return SearchAnalysis("no_candidates", [])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract exact package candidates from one configured source search page."
    )
    parser.add_argument("url", help="Configured public source search URL")
    parser.add_argument("--package-name", required=True, help="Confirmed Android package name")
    parser.add_argument("--timeout", type=float, default=20.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.timeout <= 0 or args.timeout > 60:
        raise SystemExit("--timeout must be greater than 0 and no more than 60")
    try:
        page = fetch_page(args.url, args.timeout)
        analysis = analyze_search_html(
            page.body,
            args.url,
            page.final_url,
            page.status,
            args.package_name,
        )
    except (URLError, socket.timeout, TimeoutError, ConnectionError, OSError, ValueError) as error:
        print("classification=network_error")
        print(f"error={type(error).__name__}: {error}")
        return 1

    print(f"classification={analysis.classification}")
    print(f"status={page.status}")
    print(f"search_url={args.url}")
    print(f"final_url={page.final_url}")
    print(f"candidate_count={len(analysis.links)}")
    for link in analysis.links:
        print(f"candidate_url={link}")
    return 0 if analysis.classification in {"candidate_found", "no_candidates"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
