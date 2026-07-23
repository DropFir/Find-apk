#!/usr/bin/env python3
"""Read one public page through the local Cloudflare-Faker Chrome extension."""

from __future__ import annotations

import json
import uuid
from urllib.error import HTTPError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen


FAKER_API_URL = "http://127.0.0.1:8080/api/remote-html"


class CloudflareFakerError(ConnectionError):
    """The local service or its Chrome extension could not render the page."""


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

    request = Request(
        FAKER_API_URL,
        data=json.dumps(
            {
                "pageUrl": navigation_url,
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
        raise CloudflareFakerError("Cloudflare-Faker returned invalid JSON") from error

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
