#!/usr/bin/env python3
"""Validate an existing Android package before it is reused as a deliverable."""

from __future__ import annotations

import argparse
from pathlib import Path

from download_file import PACKAGE_SUFFIXES, validate_download


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate ZIP/CRC and split completeness of a local package."
    )
    parser.add_argument("package", type=Path, help="Existing APK/XAPK/APKM/APKS")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    package = args.package.expanduser().resolve(strict=False)
    suffix = package.suffix.casefold()
    if suffix not in PACKAGE_SUFFIXES:
        print(f"classification=unsupported_format")
        print(f"package={package.as_posix()}")
        return 2
    if not package.is_file():
        print("classification=missing_file")
        print(f"package={package.as_posix()}")
        return 2
    try:
        validate_download(package, suffix, "application/octet-stream")
    except (OSError, ValueError) as error:
        print("classification=invalid_package")
        print(f"package={package.as_posix()}")
        print(f"reason={error}")
        return 1
    print("classification=valid_package")
    print(f"package={package.as_posix()}")
    print(f"format={suffix.removeprefix('.')}")
    print(f"bytes={package.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
