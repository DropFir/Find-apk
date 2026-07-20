#!/usr/bin/env python3
"""Convert an app icon to a lossless WebP without resizing it."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import uuid
from pathlib import Path

try:
    from PIL import Image, UnidentifiedImageError
except ImportError:  # pragma: no cover - exercised only before dependencies exist
    requirements = Path(__file__).resolve().parents[1] / "requirements.txt"
    print(
        f'Pillow is required. Run: python -m pip install -r "{requirements}"',
        file=sys.stderr,
    )
    raise SystemExit(2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert PNG/JPEG or another Pillow-readable icon to lossless WebP."
    )
    parser.add_argument("source", type=Path, help="Source image path")
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        help="Output .webp path; defaults to the source name with a .webp suffix",
    )
    return parser.parse_args()


def image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        if image.format != "WEBP":
            raise ValueError(f"Output is {image.format or 'unknown'}, not WEBP")
        size = image.size
        image.load()
        return size


def convert_icon(source: Path, output: Path) -> tuple[int, int]:
    source = source.expanduser().resolve(strict=True)
    output = output.expanduser()

    if output.suffix.lower() != ".webp":
        raise ValueError("Output filename must end in .webp")

    output.parent.mkdir(parents=True, exist_ok=True)
    output = output.resolve(strict=False)

    with Image.open(source) as original:
        original.seek(0)
        expected_size = original.size

    if source == output:
        actual_size = image_size(source)
        if actual_size != expected_size:
            raise ValueError("Existing WEBP dimensions changed unexpectedly")
        return actual_size

    temporary = output.parent / f".{output.name}.{uuid.uuid4().hex}.tmp.webp"

    try:
        if source.suffix.lower() == ".webp":
            shutil.copy2(source, temporary)
        else:
            with Image.open(source) as original:
                original.seek(0)
                info = original.info.copy()
                has_alpha = "A" in original.getbands() or "transparency" in info
                image = original.convert("RGBA" if has_alpha else "RGB")

                save_options: dict[str, object] = {
                    "format": "WEBP",
                    "lossless": True,
                    "method": 4,
                    "exact": True,
                }
                if info.get("icc_profile"):
                    save_options["icc_profile"] = info["icc_profile"]
                if info.get("exif"):
                    save_options["exif"] = info["exif"]

                image.save(temporary, **save_options)

        actual_size = image_size(temporary)
        if actual_size != expected_size:
            raise ValueError(
                f"Image dimensions changed from {expected_size} to {actual_size}"
            )

        os.replace(temporary, output)
        return actual_size
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    args = parse_args()
    source: Path = args.source
    output: Path = args.output or source.with_suffix(".webp")

    try:
        width, height = convert_icon(source, output)
    except (FileNotFoundError, UnidentifiedImageError, OSError, ValueError) as error:
        print(f"Icon conversion failed: {error}", file=sys.stderr)
        return 1

    print(f"{output.as_posix()} ({width}x{height}, lossless WEBP)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
