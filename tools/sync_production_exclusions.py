#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, timedelta
import json
from pathlib import Path
import sqlite3
import sys
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen


AGENT_ROOT = Path(__file__).resolve().parents[1]
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from lan_share.indexer import normalize_search_text  # noqa: E402
from lan_share.package_identity import identify_package  # noqa: E402
from lan_share.production_queue import ProductionQueue  # noqa: E402


def external_name(job: dict[str, object]) -> str:
    display_name = str(job.get("display_name") or "")
    package_name = str(job.get("package_name") or "")
    marker = f"_{package_name}_"
    if package_name and marker in display_name:
        return display_name.split(marker, 1)[0].replace("_", " ")
    return display_name.rsplit("_", 1)[0].replace("_", " ")


def fetch_summary(source_url: str, selected_date: str) -> dict[str, object]:
    url = urljoin(source_url.rstrip("/") + "/", "api/summary")
    request = Request(
        f"{url}?{urlencode({'date': selected_date})}",
        headers={"Accept": "application/json"},
    )
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def collect_external_jobs(
    source_url: str,
    *,
    maximum_days: int,
    empty_days_to_stop: int,
) -> tuple[list[dict[str, object]], list[str]]:
    selected = date.today()
    empty_days = 0
    jobs_by_id: dict[str, dict[str, object]] = {}
    checked_dates: list[str] = []
    found_data = False
    for _ in range(maximum_days):
        selected_date = selected.isoformat()
        summary = fetch_summary(source_url, selected_date)
        checked_dates.append(selected_date)
        jobs = summary.get("jobs")
        if not isinstance(jobs, list):
            raise ValueError(f"invalid jobs response for {selected_date}")
        if jobs:
            found_data = True
            empty_days = 0
            for job in jobs:
                if isinstance(job, dict):
                    identity = str(
                        job.get("id")
                        or (
                            job.get("package_name"),
                            job.get("display_name"),
                            job.get("source_date"),
                        )
                    )
                    jobs_by_id[identity] = job
        else:
            empty_days += 1
            if found_data and empty_days >= empty_days_to_stop:
                break
        selected -= timedelta(days=1)
    return list(jobs_by_id.values()), checked_dates


def local_deliveries(index_database: Path) -> list[dict[str, str]]:
    connection = sqlite3.connect(index_database)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT directory, signature, keyword, package_relpath
            FROM deliveries
            WHERE valid = 1
            ORDER BY delivery_date, keyword COLLATE NOCASE
            """
        ).fetchall()
    finally:
        connection.close()
    return [
        {
            "delivery_key": f"{row['directory']}:{row['signature']}",
            "keyword": row["keyword"],
            "package_relpath": row["package_relpath"],
        }
        for row in rows
    ]


def match_deliveries(
    deliveries: list[dict[str, str]],
    external_jobs: list[dict[str, object]],
) -> tuple[list[dict[str, str]], int]:
    by_package: dict[str, dict[str, object]] = {}
    by_name: dict[str, dict[str, object]] = {}
    for job in external_jobs:
        package_name = str(job.get("package_name") or "").strip()
        if package_name:
            by_package[package_name.casefold()] = job
        name = external_name(job)
        normalized_name = normalize_search_text(name)
        if normalized_name:
            by_name[normalized_name] = job

    matches: list[dict[str, str]] = []
    identified = 0
    for delivery in deliveries:
        package_path = (
            AGENT_ROOT / "downloads" / delivery["package_relpath"]
        ).resolve(strict=False)
        package_name = identify_package(package_path)
        job: dict[str, object] | None = None
        match_type = ""
        if package_name:
            identified += 1
            job = by_package.get(package_name.casefold())
            match_type = "package"
        else:
            job = by_name.get(normalize_search_text(delivery["keyword"]))
            match_type = "keyword"
        if job is None:
            continue
        matches.append(
            {
                "delivery_key": delivery["delivery_key"],
                "keyword": delivery["keyword"],
                "matched_name": external_name(job),
                "matched_package": str(job.get("package_name") or ""),
                "match_type": match_type,
            }
        )
    return matches, identified


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Exclude APKs already present in an APKBA monitor."
    )
    parser.add_argument("source_url")
    parser.add_argument("--maximum-days", type=int, default=90)
    parser.add_argument("--empty-days-to-stop", type=int, default=14)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source_url = args.source_url.rstrip("/") + "/"
    jobs, checked_dates = collect_external_jobs(
        source_url,
        maximum_days=max(1, args.maximum_days),
        empty_days_to_stop=max(1, args.empty_days_to_stop),
    )
    deliveries = local_deliveries(
        AGENT_ROOT / ".find-apk-share" / "index.sqlite3"
    )
    matches, identified = match_deliveries(deliveries, jobs)
    match_types = Counter(match["match_type"] for match in matches)
    states = Counter(str(job.get("state") or "unknown") for job in jobs)

    created = 0
    existing = 0
    if not args.dry_run:
        queue = ProductionQueue(
            AGENT_ROOT / ".find-apk-share" / "production.sqlite3"
        )
        queue.initialize()
        result = queue.exclude_deliveries(matches, source_url=source_url)
        created = result["created"]
        existing = result["existing"]

    print("classification=production_exclusions_synced")
    print(f"source={source_url}")
    print(f"checked_dates={len(checked_dates)}")
    print(f"external_jobs={len(jobs)}")
    print(f"external_states={json.dumps(states, ensure_ascii=False, sort_keys=True)}")
    print(f"local_deliveries={len(deliveries)}")
    print(f"local_packages_identified={identified}")
    print(f"matched={len(matches)}")
    print(f"matched_by_package={match_types['package']}")
    print(f"matched_by_keyword={match_types['keyword']}")
    print(f"newly_excluded={created}")
    print(f"already_excluded={existing}")
    print(f"dry_run={str(args.dry_run).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
