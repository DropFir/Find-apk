#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import shutil
import sqlite3
import sys


AGENT_ROOT = Path(__file__).resolve().parents[1]
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from lan_share.indexer import DeliveryIndex  # noqa: E402


DOWNLOADS_ROOT = (AGENT_ROOT / "downloads").resolve(strict=False)
STATE_ROOT = AGENT_ROOT / ".find-apk-share"


def exact_published_directories() -> list[Path]:
    production = sqlite3.connect(STATE_ROOT / "production.sqlite3")
    index = sqlite3.connect(STATE_ROOT / "index.sqlite3")
    try:
        published = {
            row[0]
            for row in production.execute(
                "SELECT delivery_key FROM production_exclusions"
            )
        }
        published.update(
            row[0]
            for row in production.execute(
                "SELECT delivery_key FROM production_external_completions"
            )
        )
        rows = index.execute(
            """
            SELECT directory, signature
            FROM deliveries
            WHERE valid = 1
            ORDER BY directory
            """
        ).fetchall()
    finally:
        production.close()
        index.close()

    directories: list[Path] = []
    for directory, signature in rows:
        if f"{directory}:{signature}" not in published:
            continue
        path = (DOWNLOADS_ROOT / directory).resolve(strict=False)
        try:
            path.relative_to(DOWNLOADS_ROOT)
        except ValueError as error:
            raise ValueError(f"unsafe delivery path: {path}") from error
        if path.is_symlink():
            raise ValueError(f"refusing symlink delivery path: {path}")
        if path.is_dir():
            directories.append(path)
    return directories


def directory_size(path: Path) -> int:
    return sum(
        entry.stat().st_size
        for entry in path.rglob("*")
        if entry.is_file()
    )


def library_count() -> int:
    connection = sqlite3.connect(STATE_ROOT / "index.sqlite3")
    try:
        return connection.execute(
            "SELECT COUNT(*) FROM deliveries WHERE valid = 1"
        ).fetchone()[0]
    finally:
        connection.close()


def refresh_index() -> bool:
    index = DeliveryIndex(
        DOWNLOADS_ROOT,
        STATE_ROOT / "index.sqlite3",
        AGENT_ROOT / "tools" / "validate_delivery.py",
    )
    index.initialize()
    return index.scan()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Move Find-APK deliveries already present in the APKBA monitor "
            "or public site to the macOS Trash."
        )
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    directories = exact_published_directories()
    matched_bytes = sum(directory_size(directory) for directory in directories)
    before = library_count()
    if args.dry_run:
        print("classification=trash_published_deliveries_preview")
        print(f"library_before={before}")
        print(f"matched_directories={len(directories)}")
        print(f"matched_bytes={matched_bytes}")
        print(f"matched_gib={matched_bytes / 1024 ** 3:.3f}")
        for directory in directories:
            print(f"matched_directory={directory.relative_to(DOWNLOADS_ROOT)}")
        return 0

    if not directories:
        print("classification=no_published_deliveries_to_trash")
        print(f"library_before={before}")
        print("matched_directories=0")
        return 0

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    trash_root = (Path.home() / ".Trash").resolve(strict=False)
    if not trash_root.is_dir():
        trash_root = (STATE_ROOT / "recovery-trash").resolve(strict=False)
    batch_root = trash_root / f"Find-APK-removed-{timestamp}"
    batch_root.mkdir(parents=True, exist_ok=False)

    moved = 0
    for directory in directories:
        relative = directory.relative_to(DOWNLOADS_ROOT)
        destination = batch_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(directory), str(destination))
        moved += 1

    refreshed = refresh_index()
    after = library_count()
    print("classification=published_deliveries_trashed")
    print(f"library_before={before}")
    print(f"matched_directories={len(directories)}")
    print(f"matched_bytes={matched_bytes}")
    print(f"matched_gib={matched_bytes / 1024 ** 3:.3f}")
    print(f"moved_directories={moved}")
    print(f"library_after={after}")
    print(f"index_refreshed={str(refreshed).lower()}")
    print(f"recovery_directory={batch_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
