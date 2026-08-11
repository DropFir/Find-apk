#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


AGENT_ROOT = Path(__file__).resolve().parents[1]
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from lan_share.queue_store import KeywordQueue  # noqa: E402


def emit(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def directory_matches_keyword(directory_name: str, keyword: str) -> bool:
    from lan_share.indexer import normalize_search_text

    directory_key = normalize_search_text(directory_name).replace(" ", "")
    keyword_key = normalize_search_text(keyword).replace(" ", "")
    return bool(directory_key and directory_key == keyword_key)


def validate_delivery(
    directory_value: str,
    *,
    expected_keyword: str,
    allow_tv: bool = False,
) -> tuple[bool, str]:
    downloads_root = (AGENT_ROOT / "downloads").resolve(strict=False)
    candidate = Path(directory_value)
    if not candidate.is_absolute():
        candidate = AGENT_ROOT / candidate
    candidate = candidate.resolve(strict=False)
    try:
        candidate.relative_to(downloads_root)
    except ValueError:
        return False, "delivery directory must stay inside downloads/"
    if not candidate.is_dir():
        return False, "delivery directory does not exist"
    if not directory_matches_keyword(candidate.name, expected_keyword):
        return (
            False,
            "delivery directory does not match the queued keyword",
        )

    validator_command = [
        sys.executable,
        str(AGENT_ROOT / "tools" / "validate_delivery.py"),
        str(candidate),
    ]
    if allow_tv:
        validator_command.append("--allow-tv")
    completed = subprocess.run(
        validator_command,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if completed.returncode != 0:
        detail = completed.stdout.strip() or completed.stderr.strip()
        return False, detail or "delivery validation failed"
    values: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value
    if values.get("classification") != "valid_delivery":
        return False, completed.stdout.strip() or "delivery is incomplete"
    return True, candidate.relative_to(AGENT_ROOT).as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manage the Find APK LAN keyword queue."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add")
    add_parser.add_argument("keywords", nargs="+")

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--status")
    list_parser.add_argument("--limit", type=int, default=100)

    claim_parser = subparsers.add_parser("claim")
    claim_parser.add_argument("--limit", type=int, default=10)
    claim_parser.add_argument("--worker", required=True)
    claim_parser.add_argument(
        "--automatic",
        action="store_true",
        help=(
            "Prioritize normal jobs and throttle exact candidates blocked by "
            "Cloudflare or browser timeouts to one every six hours."
        ),
    )

    claim_id_parser = subparsers.add_parser("claim-id")
    claim_id_parser.add_argument("--id", type=int, required=True)
    claim_id_parser.add_argument("--worker", required=True)

    complete_parser = subparsers.add_parser("complete")
    complete_parser.add_argument("--id", type=int, required=True)
    complete_parser.add_argument("--delivery-directory", required=True)
    complete_parser.add_argument("--allow-tv", action="store_true")

    paid_parser = subparsers.add_parser("paid")
    paid_parser.add_argument("--id", type=int, required=True)

    miss_parser = subparsers.add_parser("miss")
    miss_parser.add_argument("--id", type=int, required=True)
    miss_parser.add_argument("--reason", required=True)

    candidate_parser = subparsers.add_parser("candidate")
    candidate_parser.add_argument("--id", type=int, required=True)
    candidate_parser.add_argument("--url", required=True)

    clear_candidate_parser = subparsers.add_parser("clear-candidate")
    clear_candidate_parser.add_argument("--id", type=int, required=True)
    clear_candidate_parser.add_argument("--reason", required=True)

    reopen_parser = subparsers.add_parser("reopen")
    reopen_parser.add_argument("--id", type=int, required=True)
    reopen_parser.add_argument("--reason", default="")
    reopen_parser.add_argument("--candidate-url", default="")

    retry_parser = subparsers.add_parser("retry")
    retry_parser.add_argument("--id", type=int, required=True)
    retry_parser.add_argument("--reason", required=True)

    remove_parser = subparsers.add_parser("remove-pending")
    remove_parser.add_argument("--id", type=int, action="append", required=True)

    subparsers.add_parser("status")
    arguments = parser.parse_args()

    state_root = Path(
        os.environ.get(
            "FIND_APK_SHARE_STATE",
            AGENT_ROOT / ".find-apk-share",
        )
    ).resolve(strict=False)
    queue = KeywordQueue(state_root / "queue.sqlite3")
    queue.initialize()

    try:
        if arguments.command == "add":
            emit(queue.add(arguments.keywords))
            return 0
        if arguments.command == "list":
            emit(
                {
                    "jobs": [
                        job.as_json()
                        for job in queue.list_jobs(
                            status=arguments.status,
                            limit=arguments.limit,
                        )
                    ]
                }
            )
            return 0
        if arguments.command == "claim":
            jobs = queue.claim(
                limit=arguments.limit,
                worker=arguments.worker,
                automatic=arguments.automatic,
            )
            emit(
                {
                    "count": len(jobs),
                    "jobs": [job.as_json() for job in jobs],
                }
            )
            return 0
        if arguments.command == "claim-id":
            job = queue.claim_specific(
                arguments.id,
                worker=arguments.worker,
            )
            emit({"classification": "claimed", "job": job.as_json()})
            return 0
        if arguments.command == "complete":
            job = queue.get(arguments.id)
            if job is None:
                raise KeyError(arguments.id)
            valid, detail = validate_delivery(
                arguments.delivery_directory,
                expected_keyword=job.keyword,
                allow_tv=arguments.allow_tv,
            )
            if not valid:
                emit(
                    {
                        "classification": "invalid_delivery",
                        "detail": detail,
                    }
                )
                return 2
            job = queue.update(
                arguments.id,
                status="completed",
                delivery_directory=detail,
            )
            emit({"classification": "completed", "job": job.as_json()})
            return 0
        if arguments.command == "paid":
            job = queue.update(arguments.id, status="paid_skipped")
            emit({"classification": "paid_skipped", "job": job.as_json()})
            return 0
        if arguments.command == "miss":
            job = queue.record_search_miss(
                arguments.id,
                reason=arguments.reason,
            )
            classification = (
                "not_found_skipped"
                if job.status == "not_found_skipped"
                else "search_miss_recorded"
            )
            emit({"classification": classification, "job": job.as_json()})
            return 0
        if arguments.command == "candidate":
            job = queue.record_candidate(arguments.id, url=arguments.url)
            emit({"classification": "candidate_recorded", "job": job.as_json()})
            return 0
        if arguments.command == "clear-candidate":
            job = queue.clear_candidate(
                arguments.id,
                reason=arguments.reason,
            )
            classification = (
                "candidate_deferred"
                if job.candidate_url and job.status == "retry"
                else "candidate_cleared"
            )
            emit({"classification": classification, "job": job.as_json()})
            return 0
        if arguments.command == "reopen":
            job = queue.reopen(
                arguments.id,
                reason=arguments.reason,
                candidate_url=arguments.candidate_url,
            )
            emit({"classification": "reopened", "job": job.as_json()})
            return 0
        if arguments.command == "retry":
            job = queue.update(
                arguments.id,
                status="retry",
                error=arguments.reason,
            )
            emit({"classification": "retry", "job": job.as_json()})
            return 0
        if arguments.command == "remove-pending":
            jobs = queue.remove_pending(arguments.id)
            emit(
                {
                    "classification": "pending_removed",
                    "count": len(jobs),
                    "jobs": [job.as_json() for job in jobs],
                }
            )
            return 0
        if arguments.command == "status":
            emit(queue.snapshot())
            return 0
    except (KeyError, ValueError) as error:
        emit({"classification": "queue_error", "detail": str(error)})
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
