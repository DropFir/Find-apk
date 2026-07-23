#!/usr/bin/env python3
"""Build the configured source searches for one app without writing audit files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import quote_plus, urlparse


AGENT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = AGENT_ROOT / "sources.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Print every enabled preferred-source search for one app."
    )
    parser.add_argument("keyword", help="Original user keyword")
    parser.add_argument("--package-name", help="Confirmed Android package name")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    return parser.parse_args()


def build_searches(
    config: dict[str, object], keyword: str, package_name: str | None = None
) -> list[dict[str, str]]:
    searches: list[dict[str, str]] = []
    terms = [("keyword", keyword)]
    if package_name and package_name.casefold() != keyword.casefold():
        terms.append(("package", package_name))

    for source in config.get("preferredSources", []):
        if not isinstance(source, dict) or not source.get("enabled", False):
            continue
        name = str(source.get("name", "unnamed"))
        base_url = str(source.get("baseUrl", ""))
        template = source.get("searchUrlTemplate")
        mode = source.get("searchMode")

        for term_type, term in terms:
            domain = urlparse(base_url).netloc if base_url else ""
            fallback_target = f'site:{domain} "{term}" APK' if domain else ""
            if isinstance(template, str) and "{query}" in template:
                searches.append(
                    {
                        "source": name,
                        "term_type": term_type,
                        "method": "search_url",
                        "target": template.replace("{query}", quote_plus(term)),
                        "fallback_target": fallback_target,
                    }
                )
            elif mode == "externalSiteQuery" and base_url:
                searches.append(
                    {
                        "source": name,
                        "term_type": term_type,
                        "method": "external_query",
                        "target": fallback_target,
                        "fallback_target": "",
                    }
                )
            elif base_url:
                searches.append(
                    {
                        "source": name,
                        "term_type": term_type,
                        "method": "site_search",
                        "target": base_url,
                        "fallback_target": fallback_target,
                    }
                )

    if package_name:
        for source in config.get("publicDownloaderFallbacks", []):
            if not isinstance(source, dict) or not source.get("enabled", False):
                continue
            entry_url = str(source.get("entryUrl", ""))
            if not entry_url:
                continue
            searches.append(
                {
                    "source": str(source.get("name", "unnamed")),
                    "term_type": "package",
                    "method": "browser_generator",
                    "target": entry_url,
                    "fallback_target": "",
                }
            )
    return searches


def main() -> int:
    args = parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    searches = build_searches(config, args.keyword, args.package_name)
    for search in searches:
        print(
            "\t".join(
                (
                    search["source"],
                    search["term_type"],
                    search["method"],
                    search["target"],
                    search["fallback_target"],
                )
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
