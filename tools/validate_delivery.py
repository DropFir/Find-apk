#!/usr/bin/env python3
"""Validate a complete Find-APK keyword delivery directory."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import UnidentifiedImageError

from convert_icon import image_size
from download_file import PACKAGE_SUFFIXES, validate_download


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate that a keyword directory contains a valid Android package, "
            "a readable WEBP icon, and a single-line developer.txt."
        )
    )
    parser.add_argument("directory", type=Path, help="Keyword delivery directory")
    return parser.parse_args()


def package_sort_key(path: Path) -> tuple[bool, str]:
    return ("pending" in path.name.casefold(), path.name.casefold())


def find_valid_package(directory: Path) -> tuple[Path | None, list[str]]:
    candidates = sorted(
        (
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.casefold() in PACKAGE_SUFFIXES
        ),
        key=package_sort_key,
    )
    errors: list[str] = []
    for package in candidates:
        suffix = package.suffix.casefold()
        try:
            validate_download(package, suffix, "application/octet-stream")
        except (OSError, ValueError) as error:
            errors.append(f"{package.name}: {error}")
            continue
        return package, errors
    return None, errors


def find_valid_icon(directory: Path) -> tuple[Path | None, list[str]]:
    errors: list[str] = []
    for icon in sorted(directory.glob("*.webp")):
        try:
            width, height = image_size(icon)
            if width < 1 or height < 1:
                raise ValueError("image has invalid dimensions")
        except (OSError, UnidentifiedImageError, ValueError) as error:
            errors.append(f"{icon.name}: {error}")
            continue
        return icon, errors
    return None, errors


def read_developer(directory: Path) -> tuple[Path | None, str | None]:
    developer_file = directory / "developer.txt"
    if not developer_file.is_file():
        return None, "developer.txt is missing"
    try:
        text = developer_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return None, str(error)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) != 1:
        return None, "developer.txt must contain exactly one non-empty line"
    return developer_file, None


def main() -> int:
    args = parse_args()
    directory = args.directory.expanduser().resolve(strict=False)
    if not directory.is_dir():
        print("classification=invalid_delivery")
        print(f"directory={directory.as_posix()}")
        print("reason=delivery directory is missing")
        return 1

    package, package_errors = find_valid_package(directory)
    icon, icon_errors = find_valid_icon(directory)
    developer, developer_error = read_developer(directory)

    reasons: list[str] = []
    if package is None:
        reasons.append(
            "no valid APK/XAPK/APKM/APKS"
            + (f" ({'; '.join(package_errors)})" if package_errors else "")
        )
    if icon is None:
        reasons.append(
            "no valid WEBP icon"
            + (f" ({'; '.join(icon_errors)})" if icon_errors else "")
        )
    if developer is None:
        reasons.append(developer_error or "developer.txt is invalid")

    if reasons:
        print("classification=invalid_delivery")
        print(f"directory={directory.as_posix()}")
        for reason in reasons:
            print(f"reason={reason}")
        return 1

    print("classification=valid_delivery")
    print(f"directory={directory.as_posix()}")
    print(f"package={package.as_posix()}")
    print(f"icon={icon.as_posix()}")
    print(f"developer={developer.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
