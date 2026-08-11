#!/usr/bin/env python3
"""Download trusted public split APK links and assemble one validated XAPK."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
from urllib.parse import parse_qs, unquote, urlparse
import zipfile

from download_file import (
    acquire_download_lock,
    release_download_lock,
    select_base_apk_entry,
    validate_apk_component,
    validate_download,
)


TOOLS_DIR = Path(__file__).resolve().parent
DOWNLOAD_TOOL = TOOLS_DIR / "download_file.py"
DEFAULT_ALLOWED_HOSTS = {
    "downloads.androidcontents.com",
    "pool.apk.aptoide.com",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download confirmed MI9 or Aptoide base/split APK links "
            "and atomically assemble a validated XAPK."
        )
    )
    parser.add_argument("output", type=Path, help="Destination .xapk path")
    parser.add_argument("--package-name", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--app-name", required=True)
    parser.add_argument(
        "--split-url",
        action="append",
        default=[],
        help="One trusted APK component URL; repeat for every base/config APK",
    )
    parser.add_argument("--version-code", default="0")
    parser.add_argument("--min-sdk-version", default="0")
    parser.add_argument("--target-sdk-version", default="0")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--retries", type=int, choices=(0, 1), default=1)
    parser.add_argument(
        "--allow-tv",
        action="store_true",
        help="Allow an Android TV-only package for an explicit TV request.",
    )
    return parser.parse_args()


def component_filename(
    url: str,
    expected_package: str,
    allowed_hosts: set[str] | None = None,
) -> str:
    """Return a safe APK basename from one trusted component URL."""
    hosts = allowed_hosts or DEFAULT_ALLOWED_HOSTS
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").casefold()
    if parsed.scheme.casefold() != "https" or hostname not in hosts:
        raise ValueError("split URL is not on an allowed HTTPS download host")

    path_parts = [
        unquote(part) for part in PurePosixPath(parsed.path).parts if part != "/"
    ]
    if hostname == "pool.apk.aptoide.com":
        if not path_parts:
            raise ValueError("Aptoide split URL has no APK filename")
        filename = Path(path_parts[-1]).name
        package_slug = expected_package.replace(".", "-").replace("_", "-").casefold()
        if (
            filename != path_parts[-1]
            or not filename.casefold().endswith(".apk")
            or not filename.casefold().startswith(f"{package_slug}-")
        ):
            raise ValueError("Aptoide split URL path does not match the expected package")
        config_marker = "-config-"
        marker_index = filename.casefold().rfind(config_marker)
        if marker_index >= 0:
            config_name = filename[marker_index + len(config_marker) : -4]
            for abi_name in (
                "arm64-v8a",
                "armeabi-v7a",
                "x86-64",
            ):
                if config_name.casefold() == abi_name:
                    config_name = abi_name.replace("-", "_")
                    break
            return f"config.{config_name}.apk"
        return filename

    if not path_parts or path_parts[0].casefold() != expected_package.casefold():
        raise ValueError("split URL path does not match the expected package")

    filenames = parse_qs(parsed.query).get("filename", [])
    if len(filenames) != 1:
        raise ValueError("split URL must contain exactly one filename parameter")
    filename = Path(unquote(filenames[0])).name
    if filename != unquote(filenames[0]) or not filename.casefold().endswith(".apk"):
        raise ValueError("split URL filename is not a safe APK basename")
    return filename


def normalize_components(
    urls: list[str],
    expected_package: str,
    allowed_hosts: set[str] | None = None,
) -> list[tuple[str, str]]:
    if len(urls) < 2:
        raise ValueError("at least one base APK and one split APK are required")
    components: list[tuple[str, str]] = []
    seen: set[str] = set()
    for url in urls:
        filename = component_filename(url, expected_package, allowed_hosts)
        folded = filename.casefold()
        if folded in seen:
            raise ValueError(f"duplicate split filename: {filename}")
        seen.add(folded)
        components.append((filename, url))

    base = select_base_apk_entry([filename for filename, _ in components])
    if base is None:
        raise ValueError("could not identify exactly one base APK")
    if all(filename == base for filename, _ in components):
        raise ValueError("result contains no configuration split APK")
    return components


def xapk_entry_names(
    component_names: list[str],
    package_name: str,
) -> tuple[str, dict[str, str]]:
    base = select_base_apk_entry(component_names)
    if base is None:
        raise ValueError("could not identify exactly one base APK")
    archive_names = {
        name: (f"{package_name}.apk" if name == base else name)
        for name in component_names
    }
    return base, archive_names


def write_xapk(
    component_paths: list[Path],
    output: Path,
    *,
    package_name: str,
    app_name: str,
    version: str,
    version_code: str = "0",
    min_sdk_version: str = "0",
    target_sdk_version: str = "0",
    allow_tv: bool = False,
) -> None:
    """Create an APKPure-compatible XAPK manifest and validate the result."""
    component_names = [path.name for path in component_paths]
    base, archive_names = xapk_entry_names(component_names, package_name)
    split_apks = []
    split_configs = []
    total_size = 0
    for component in component_paths:
        archive_name = archive_names[component.name]
        split_id = "base" if component.name == base else Path(archive_name).stem
        if split_id != "base":
            split_configs.append(split_id)
        split_apks.append({"file": archive_name, "id": split_id})
        total_size += component.stat().st_size

    manifest = {
        "xapk_version": 2,
        "package_name": package_name,
        "name": app_name,
        "version_code": str(version_code),
        "version_name": version,
        "min_sdk_version": str(min_sdk_version),
        "target_sdk_version": str(target_sdk_version),
        "permissions": [],
        "split_configs": split_configs,
        "total_size": total_size,
        "split_apks": split_apks,
    }

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for component in component_paths:
            archive.write(component, archive_names[component.name])
        archive.writestr(
            "manifest.json",
            json.dumps(
                manifest,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8"),
        )
    validate_download(
        output,
        ".xapk",
        "application/octet-stream",
        allow_tv=allow_tv,
    )


def main() -> int:
    args = parse_args()
    if args.timeout <= 0 or args.timeout > 60:
        raise SystemExit("--timeout must be greater than 0 and no more than 60")
    output = args.output.expanduser().resolve(strict=False)
    if output.suffix.casefold() != ".xapk":
        raise SystemExit("output must use the .xapk extension")

    try:
        components = normalize_components(args.split_url, args.package_name)
    except ValueError as error:
        print("classification=invalid_split_links")
        print(f"error={error}")
        return 2

    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        output_lock = acquire_download_lock(output)
    except (OSError, RuntimeError) as error:
        print(f"Download failed: {error}", file=sys.stderr)
        return 1

    building = output.parent / f".{output.name}.building"
    building.unlink(missing_ok=True)
    try:
        component_directory = output.parent / f".{output.stem}-components"
        component_directory.mkdir(parents=True, exist_ok=True)
        directory = component_directory
        try:
            component_paths: list[Path] = []
            for filename, url in components:
                component = directory / filename
                if component.is_file():
                    try:
                        validate_apk_component(component)
                    except (OSError, ValueError, zipfile.BadZipFile):
                        pass
                    else:
                        component_paths.append(component)
                        continue
                command = [
                    sys.executable,
                    str(DOWNLOAD_TOOL),
                    url,
                    str(component),
                    "--timeout",
                    f"{args.timeout:g}",
                    "--retries",
                    str(args.retries),
                    "--split-component",
                ]
                completed = subprocess.run(command, check=False)
                if completed.returncode != 0:
                    print("classification=split_download_failed")
                    print(f"failed_component={filename}")
                    return 1
                component_paths.append(component)

            try:
                write_xapk(
                    component_paths,
                    building,
                    package_name=args.package_name,
                    app_name=args.app_name,
                    version=args.version,
                    version_code=args.version_code,
                    min_sdk_version=args.min_sdk_version,
                    target_sdk_version=args.target_sdk_version,
                    allow_tv=args.allow_tv,
                )
            except (OSError, ValueError, zipfile.BadZipFile) as error:
                print("classification=invalid_split_archive")
                print(f"error={error}")
                return 1

            os.replace(building, output)
            shutil.rmtree(component_directory, ignore_errors=True)
            print("classification=valid_split_archive")
            print("pipeline_result=saved")
            print(f"package_name={args.package_name}")
            print(f"version={args.version}")
            print(f"component_count={len(component_paths)}")
            print(f"output={output.as_posix()}")
            print(f"bytes={output.stat().st_size}")
            return 0
        except Exception:
            # Preserve completed components and resumable partials for the next
            # invocation. The output lock prevents concurrent writers.
            raise
    finally:
        building.unlink(missing_ok=True)
        release_download_lock(output_lock)


if __name__ == "__main__":
    raise SystemExit(main())
