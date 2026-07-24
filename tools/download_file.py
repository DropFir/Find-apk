#!/usr/bin/env python3
"""Download one public asset atomically and reject HTML masquerading as a file."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from http.client import HTTPException, IncompleteRead
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from http_headers import BROWSER_NAVIGATION_HEADERS

BROWSER_HEADERS = {
    "User-Agent": BROWSER_NAVIGATION_HEADERS["User-Agent"],
    "Accept": "*/*",
    "Accept-Language": BROWSER_NAVIGATION_HEADERS["Accept-Language"],
}
PACKAGE_SUFFIXES = {".apk", ".xapk", ".apkm", ".apks"}
ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
CHUNK_SIZE = 1024 * 1024
INSPECT_SIZE = 512
LARGE_PACKAGE_BYTES = 50 * 1024 * 1024
LARGE_PACKAGE_MIN_TIMEOUT = 60.0
LARGE_PACKAGE_MAX_TIMEOUT = 900.0
LARGE_PACKAGE_MIN_BYTES_PER_SECOND = 512 * 1024
DEX_ENTRY_PATTERN = re.compile(r"^classes(?:[0-9]+)?\.dex$")
SPLIT_DESCRIPTOR_PATTERN = re.compile(r"^res/xml/splits[^/]*\.xml$")
NATIVE_ENGINE_MARKERS = (
    b"cocos2dcpp",
    b"android_cocos2dx",
    b"com/unity3d/player/UnityPlayer",
    b"com/unity3d/player/NativeLoader",
    b"libil2cpp.so",
    b"libUE4.so",
    b"libgodot_android.so",
)
MARKER_OVERLAP = max(len(marker) for marker in NATIVE_ENGINE_MARKERS) - 1
ABI_SPLIT_PATTERN = re.compile(
    r"(?:^|[._-])(?:arm64[_-]?v8a|armeabi[_-]?v7a|armeabi|x86_64|x86)(?:[._-]|$)",
    re.IGNORECASE,
)
DENSITY_SPLIT_PATTERN = re.compile(
    r"(?:^|[._-])(?:ldpi|mdpi|tvdpi|hdpi|xhdpi|xxhdpi|xxxhdpi|[1-9][0-9]{2,3}dpi)"
    r"(?:[._-]|$)",
    re.IGNORECASE,
)
ANDROID_BINARY_XML_TYPE = 0x0003
STRING_POOL_TYPE = 0x0001
START_ELEMENT_TYPE = 0x0102
UTF8_STRING_POOL_FLAG = 0x00000100
TYPE_STRING = 0x03
TYPE_INT_BOOLEAN = 0x12
NO_STRING_INDEX = 0xFFFFFFFF


@dataclass(frozen=True)
class ManifestSplitInfo:
    """Split-delivery declarations read from AndroidManifest.xml."""

    required_types: frozenset[str] = frozenset()
    splits_required: bool = False
    split_name: str | None = None

    @property
    def requires_components(self) -> bool:
        return self.splits_required or bool(self.required_types)


def _read_length8(data: bytes, offset: int) -> tuple[int, int]:
    first = data[offset]
    if first & 0x80:
        return ((first & 0x7F) << 8) | data[offset + 1], offset + 2
    return first, offset + 1


def _read_length16(data: bytes, offset: int) -> tuple[int, int]:
    first = int.from_bytes(data[offset : offset + 2], "little")
    if first & 0x8000:
        second = int.from_bytes(data[offset + 2 : offset + 4], "little")
        return ((first & 0x7FFF) << 16) | second, offset + 4
    return first, offset + 2


def _parse_binary_xml_string_pool(data: bytes, offset: int) -> list[str]:
    header_size = int.from_bytes(data[offset + 2 : offset + 4], "little")
    chunk_size = int.from_bytes(data[offset + 4 : offset + 8], "little")
    string_count = int.from_bytes(data[offset + 8 : offset + 12], "little")
    flags = int.from_bytes(data[offset + 16 : offset + 20], "little")
    strings_start = int.from_bytes(data[offset + 20 : offset + 24], "little")
    if (
        header_size < 28
        or chunk_size < header_size
        or offset + chunk_size > len(data)
        or string_count > (chunk_size - header_size) // 4
    ):
        raise ValueError("invalid Android binary XML string pool")

    utf8 = bool(flags & UTF8_STRING_POOL_FLAG)
    strings: list[str] = []
    offsets_start = offset + header_size
    content_start = offset + strings_start
    chunk_end = offset + chunk_size
    for index in range(string_count):
        relative = int.from_bytes(
            data[offsets_start + index * 4 : offsets_start + index * 4 + 4],
            "little",
        )
        position = content_start + relative
        if position >= chunk_end:
            raise ValueError("invalid Android binary XML string offset")
        if utf8:
            _, position = _read_length8(data, position)
            byte_length, position = _read_length8(data, position)
            end = position + byte_length
            if end > chunk_end:
                raise ValueError("truncated Android binary XML UTF-8 string")
            strings.append(data[position:end].decode("utf-8", errors="replace"))
        else:
            char_length, position = _read_length16(data, position)
            end = position + char_length * 2
            if end > chunk_end:
                raise ValueError("truncated Android binary XML UTF-16 string")
            strings.append(data[position:end].decode("utf-16le", errors="replace"))
    return strings


def _string_at(strings: list[str], index: int) -> str | None:
    if index == NO_STRING_INDEX:
        return None
    if 0 <= index < len(strings):
        return strings[index]
    raise ValueError("invalid Android binary XML string reference")


def _parse_binary_manifest_attributes(
    data: bytes,
) -> list[tuple[str, dict[str, str | bool | int | None]]]:
    if len(data) < 8:
        return []
    xml_type = int.from_bytes(data[0:2], "little")
    xml_size = int.from_bytes(data[4:8], "little")
    if xml_type != ANDROID_BINARY_XML_TYPE:
        return []
    if xml_size > len(data) or xml_size < 8:
        raise ValueError("invalid Android binary XML document size")

    strings: list[str] | None = None
    elements: list[tuple[str, dict[str, str | bool | int | None]]] = []
    offset = 8
    while offset + 8 <= xml_size:
        chunk_type = int.from_bytes(data[offset : offset + 2], "little")
        header_size = int.from_bytes(data[offset + 2 : offset + 4], "little")
        chunk_size = int.from_bytes(data[offset + 4 : offset + 8], "little")
        if (
            header_size < 8
            or chunk_size < header_size
            or offset + chunk_size > xml_size
        ):
            raise ValueError("invalid Android binary XML chunk")
        if chunk_type == STRING_POOL_TYPE:
            strings = _parse_binary_xml_string_pool(data, offset)
        elif chunk_type == START_ELEMENT_TYPE:
            if strings is None or header_size < 16 or chunk_size < header_size + 20:
                raise ValueError("invalid Android binary XML start element")
            extension = offset + header_size
            element_name = _string_at(
                strings,
                int.from_bytes(data[extension + 4 : extension + 8], "little"),
            )
            attribute_start = int.from_bytes(
                data[extension + 8 : extension + 10], "little"
            )
            attribute_size = int.from_bytes(
                data[extension + 10 : extension + 12], "little"
            )
            attribute_count = int.from_bytes(
                data[extension + 12 : extension + 14], "little"
            )
            if attribute_size < 20:
                raise ValueError("invalid Android binary XML attribute size")
            attributes: dict[str, str | bool | int | None] = {}
            attribute_offset = extension + attribute_start
            for attribute_index in range(attribute_count):
                item = attribute_offset + attribute_index * attribute_size
                if item + 20 > offset + chunk_size:
                    raise ValueError("truncated Android binary XML attribute")
                name = _string_at(
                    strings, int.from_bytes(data[item + 4 : item + 8], "little")
                )
                raw_value = _string_at(
                    strings, int.from_bytes(data[item + 8 : item + 12], "little")
                )
                data_type = data[item + 15]
                typed_data = int.from_bytes(data[item + 16 : item + 20], "little")
                if raw_value is not None:
                    value: str | bool | int | None = raw_value
                elif data_type == TYPE_STRING:
                    value = _string_at(strings, typed_data)
                elif data_type == TYPE_INT_BOOLEAN:
                    value = bool(typed_data)
                else:
                    value = typed_data
                if name is not None:
                    attributes[name] = value
            if element_name is not None:
                elements.append((element_name, attributes))
        offset += chunk_size
    return elements


def inspect_manifest_split_info(manifest: bytes) -> ManifestSplitInfo:
    """Read explicit App Bundle split requirements without Android SDK tools."""
    elements = _parse_binary_manifest_attributes(manifest)
    if not elements and manifest.lstrip().startswith(b"<"):
        import xml.etree.ElementTree as ElementTree

        try:
            root = ElementTree.fromstring(manifest)
        except ElementTree.ParseError as error:
            raise ValueError("invalid text AndroidManifest.xml") from error
        elements = []
        for element in root.iter():
            tag = element.tag.rsplit("}", 1)[-1]
            attributes = {
                name.rsplit("}", 1)[-1]: value
                for name, value in element.attrib.items()
            }
            elements.append((tag, attributes))

    required_types: set[str] = set()
    splits_required = False
    split_name: str | None = None
    for tag, attributes in elements:
        if tag == "manifest":
            raw_required = attributes.get("requiredSplitTypes")
            if isinstance(raw_required, str):
                required_types.update(
                    item.strip()
                    for item in re.split(r"[,;\s]+", raw_required)
                    if item.strip()
                )
            raw_split_name = attributes.get("split")
            if isinstance(raw_split_name, str) and raw_split_name.strip():
                split_name = raw_split_name.strip()
        elif (
            tag in {"meta-data", "metadata"}
            and attributes.get("name") == "com.android.vending.splits.required"
        ):
            value = attributes.get("value")
            splits_required = value is True or (
                isinstance(value, str) and value.casefold() == "true"
            )
    return ManifestSplitInfo(
        required_types=frozenset(required_types),
        splits_required=splits_required,
        split_name=split_name,
    )


def inspect_apk_manifest(archive: zipfile.ZipFile) -> ManifestSplitInfo:
    try:
        manifest = archive.read("AndroidManifest.xml")
    except KeyError as error:
        raise ValueError("Android package is missing AndroidManifest.xml") from error
    return inspect_manifest_split_info(manifest)


def format_required_split_types(required_types: frozenset[str]) -> str:
    labels: list[str] = []
    if any("abi" in item.casefold() for item in required_types):
        labels.append("ABI")
    if any("density" in item.casefold() for item in required_types):
        labels.append("density")
    if not labels:
        labels.extend(sorted(required_types))
    return "/".join(labels) or "configuration"


def archive_entry_contains_native_engine_marker(
    archive: zipfile.ZipFile, entry_name: str
) -> bool:
    """Scan a DEX incrementally for high-confidence native game engine markers."""
    tail = b""
    with archive.open(entry_name) as entry:
        while chunk := entry.read(CHUNK_SIZE):
            inspected = tail + chunk
            if any(marker in inspected for marker in NATIVE_ENGINE_MARKERS):
                return True
            tail = inspected[-MARKER_OVERLAP:]
    return False


def inspect_apk_archive(archive: zipfile.ZipFile) -> tuple[bool, bool, bool]:
    names = set(archive.namelist())
    has_native_library = any(
        name.startswith("lib/") and name.casefold().endswith(".so") for name in names
    )
    has_split_descriptor = any(
        SPLIT_DESCRIPTOR_PATTERN.fullmatch(name) for name in names
    )
    dex_entries = [name for name in names if DEX_ENTRY_PATTERN.fullmatch(name)]
    requires_native_engine = any(
        archive_entry_contains_native_engine_marker(archive, name)
        for name in dex_entries
    )
    return has_native_library, has_split_descriptor, requires_native_engine


def validate_apk_split_completeness(path: Path) -> None:
    """Reject an App Bundle base APK that clearly lacks its required ABI split."""
    try:
        with zipfile.ZipFile(path) as archive:
            bad_entry = archive.testzip()
            if bad_entry is not None:
                raise ValueError(f"Android package failed ZIP/CRC validation: {bad_entry}")
            split_info = inspect_apk_manifest(archive)
            if split_info.requires_components:
                required = format_required_split_types(split_info.required_types)
                raise ValueError(
                    "APK is a split-required App Bundle base APK missing its "
                    f"required {required} split; download the matching "
                    "XAPK/APKM/APKS instead"
                )
            has_native_library, has_split_descriptor, requires_native_engine = (
                inspect_apk_archive(archive)
            )
            if (
                not has_native_library
                and has_split_descriptor
                and requires_native_engine
            ):
                raise ValueError(
                    "APK is an App Bundle base package missing its required ABI "
                    "split; download the matching XAPK/APKM/APKS instead"
                )
    except zipfile.BadZipFile as error:
        raise ValueError("download is not a valid ZIP-based Android package") from error


def validate_apk_component(path: Path) -> None:
    """Validate one APK component without requiring it to be standalone."""
    try:
        with zipfile.ZipFile(path) as archive:
            bad_entry = archive.testzip()
            if bad_entry is not None:
                raise ValueError(
                    f"Android package failed ZIP/CRC validation: {bad_entry}"
                )
    except zipfile.BadZipFile as error:
        raise ValueError("download is not a valid ZIP-based Android package") from error


def inspect_nested_apk(
    outer_archive: zipfile.ZipFile, entry_name: str
) -> tuple[bool, bool, bool]:
    """Inspect one nested APK without keeping another permanent copy on disk."""
    with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as nested_file:
        with outer_archive.open(entry_name) as source:
            shutil.copyfileobj(source, nested_file, CHUNK_SIZE)
        nested_file.seek(0)
        with zipfile.ZipFile(nested_file) as nested_archive:
            bad_entry = nested_archive.testzip()
            if bad_entry is not None:
                raise ValueError(
                    f"nested APK failed ZIP/CRC validation: {entry_name}:{bad_entry}"
                )
            return inspect_apk_archive(nested_archive)


def inspect_nested_apk_manifest(
    outer_archive: zipfile.ZipFile, entry_name: str
) -> ManifestSplitInfo:
    """Read one nested APK manifest without keeping another permanent copy."""
    with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as nested_file:
        with outer_archive.open(entry_name) as source:
            shutil.copyfileobj(source, nested_file, CHUNK_SIZE)
        nested_file.seek(0)
        with zipfile.ZipFile(nested_file) as nested_archive:
            return inspect_apk_manifest(nested_archive)


def select_base_apk_entry(apk_entries: list[str]) -> str | None:
    """Choose the most likely base APK while avoiding configuration splits."""
    for entry in apk_entries:
        basename = Path(entry).name.casefold()
        if basename in {"base.apk", "base-master.apk"}:
            return entry
    non_split_entries = [
        entry
        for entry in apk_entries
        if not Path(entry).name.casefold().startswith(
            ("config.", "split_config.", "split-", "split_")
        )
        and not ABI_SPLIT_PATTERN.search(Path(entry).stem)
    ]
    if len(non_split_entries) == 1:
        return non_split_entries[0]
    if len(apk_entries) == 1:
        return apk_entries[0]
    return None


def validate_split_package_completeness(path: Path) -> None:
    """Validate the outer archive and required native ABI split when identifiable."""
    try:
        with zipfile.ZipFile(path) as outer_archive:
            bad_entry = outer_archive.testzip()
            if bad_entry is not None:
                raise ValueError(
                    f"Android split package failed ZIP/CRC validation: {bad_entry}"
                )
            apk_entries = sorted(
                name
                for name in outer_archive.namelist()
                if name.casefold().endswith(".apk") and not name.endswith("/")
            )
            if not apk_entries:
                raise ValueError("Android split package contains no APK files")

            base_entry = select_base_apk_entry(apk_entries)
            if base_entry is None:
                return
            base_manifest = inspect_nested_apk_manifest(outer_archive, base_entry)
            component_labels: list[str] = []
            for entry in apk_entries:
                if entry == base_entry:
                    continue
                component_manifest = inspect_nested_apk_manifest(outer_archive, entry)
                component_labels.append(Path(entry).stem)
                if component_manifest.split_name:
                    component_labels.append(component_manifest.split_name)

            for required_type in sorted(base_manifest.required_types):
                normalized = required_type.casefold()
                if "abi" in normalized:
                    present = any(
                        ABI_SPLIT_PATTERN.search(label) for label in component_labels
                    )
                elif "density" in normalized:
                    present = any(
                        DENSITY_SPLIT_PATTERN.search(label)
                        for label in component_labels
                    )
                else:
                    present = bool(component_labels)
                if not present:
                    label = format_required_split_types(frozenset({required_type}))
                    raise ValueError(
                        "Android split package is missing its manifest-required "
                        f"{label} split"
                    )
            if base_manifest.splits_required and len(apk_entries) == 1:
                raise ValueError(
                    "Android split package contains only a base APK but its "
                    "manifest requires configuration splits"
                )

            base_has_library, base_has_descriptor, base_requires_native = (
                inspect_nested_apk(outer_archive, base_entry)
            )
            if base_has_library or not (
                base_has_descriptor and base_requires_native
            ):
                return

            abi_entries = [
                entry
                for entry in apk_entries
                if entry != base_entry
                and ABI_SPLIT_PATTERN.search(Path(entry).stem)
            ]
            if not any(
                inspect_nested_apk(outer_archive, entry)[0] for entry in abi_entries
            ):
                raise ValueError(
                    "Android split package is missing a required ABI APK containing "
                    "native libraries"
                )
    except zipfile.BadZipFile as error:
        raise ValueError("download is not a valid ZIP-based Android package") from error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download a public APK or image with one bounded retry."
    )
    parser.add_argument("url", help="Direct public file URL")
    parser.add_argument("output", type=Path, help="Destination file path")
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Socket timeout in seconds (default: 20)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        choices=(0, 1),
        default=1,
        help="Number of retries after a network or server error (default: 1)",
    )
    parser.add_argument(
        "--split-component",
        action="store_true",
        help=(
            "Validate an APK as one component of a split archive. "
            "Only tools/download_split_archive.py should normally use this."
        ),
    )
    return parser.parse_args()


def process_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def acquire_download_lock(output: Path) -> Path:
    """Prevent two agents from writing or renaming the same partial file."""
    lock = output.parent / f".{output.name}.lock"
    for attempt in range(2):
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            recorded = lock.read_text(encoding="utf-8", errors="replace").strip()
            if recorded.isdigit() and process_is_running(int(recorded)):
                raise RuntimeError(
                    f"another download is already writing target: {output}"
                )
            if attempt == 0:
                lock.unlink(missing_ok=True)
                continue
            raise RuntimeError(f"could not acquire download lock: {lock}")
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as record:
            record.write(f"{os.getpid()}\n")
        return lock
    raise RuntimeError(f"could not acquire download lock: {lock}")


def release_download_lock(lock: Path) -> None:
    recorded = lock.read_text(encoding="utf-8", errors="replace").strip() if lock.exists() else ""
    if recorded == str(os.getpid()):
        lock.unlink(missing_ok=True)


def validate_download(
    path: Path,
    suffix: str,
    content_type: str,
    *,
    allow_split_component: bool = False,
) -> None:
    with path.open("rb") as downloaded:
        prefix = downloaded.read(INSPECT_SIZE)

    lowered = prefix.lstrip().lower()
    normalized_type = content_type.partition(";")[0].strip().lower()
    if normalized_type in {"text/html", "application/xhtml+xml"} or lowered.startswith(
        (b"<!doctype html", b"<html", b"<head", b"<body")
    ):
        raise ValueError("server returned HTML instead of the requested file")

    if suffix in PACKAGE_SUFFIXES and not prefix.startswith(ZIP_SIGNATURES):
        raise ValueError("download is not a ZIP-based Android package")
    if suffix == ".apk":
        if allow_split_component:
            validate_apk_component(path)
        else:
            validate_apk_split_completeness(path)
    elif suffix in {".xapk", ".apkm", ".apks"}:
        validate_split_package_completeness(path)
    if suffix == ".webp" and not (
        prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP"
    ):
        raise ValueError("download is not a WEBP image")
    if not prefix:
        raise ValueError("downloaded file is empty")


def set_read_timeout(response: object, timeout: float) -> None:
    """Apply the remaining deadline to urllib's underlying socket when available."""
    for path in (
        ("fp", "fp", "raw", "_sock"),
        ("fp", "raw", "_sock"),
        ("raw", "_sock"),
        ("_sock",),
    ):
        current = response
        for attribute in path:
            current = getattr(current, attribute, None)
            if current is None:
                break
        settimeout = getattr(current, "settimeout", None)
        if settimeout is not None:
            settimeout(max(timeout, 0.001))
            return


def effective_download_timeout(
    requested: float, suffix: str, expected_length: int | None = None
) -> float:
    if suffix in PACKAGE_SUFFIXES and (
        expected_length is None or expected_length >= LARGE_PACKAGE_BYTES
    ):
        if expected_length is None:
            size_budget = LARGE_PACKAGE_MAX_TIMEOUT
        else:
            size_budget = min(
                LARGE_PACKAGE_MAX_TIMEOUT,
                max(
                    LARGE_PACKAGE_MIN_TIMEOUT,
                    expected_length / LARGE_PACKAGE_MIN_BYTES_PER_SECOND,
                ),
            )
        return max(requested, size_budget)
    return requested


def download_once(
    url: str, temporary: Path, timeout: float, suffix: str
) -> tuple[str, str, int]:
    started = time.monotonic()
    request = Request(url, headers=BROWSER_HEADERS, method="GET")
    with urlopen(request, timeout=timeout) as response, temporary.open("wb") as output:
        content_type = response.headers.get("Content-Type", "")
        content_length = response.headers.get("Content-Length", "")
        expected_length = int(content_length) if content_length.isdigit() else None
        transfer_timeout = effective_download_timeout(timeout, suffix, expected_length)
        deadline = started + transfer_timeout
        total = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"download exceeded {transfer_timeout:g} seconds"
                )
            set_read_timeout(response, remaining)
            chunk = response.read(CHUNK_SIZE)
            if not chunk:
                break
            output.write(chunk)
            total += len(chunk)
        if expected_length is not None and total != expected_length:
            raise IncompleteRead(b"", expected_length - total)
        return response.geturl(), content_type, total


def download_with_curl(
    url: str, temporary: Path, timeout: float
) -> tuple[str, str, int]:
    curl = shutil.which("curl")
    if curl is None:
        raise OSError("curl is unavailable for the fallback download attempt")

    marker = "__FIND_APK_CURL_META__"
    command = [
        curl,
        # Some APK CDNs close macOS curl's negotiated HTTP/2 connection even
        # though the same HTTPS URL works over IPv4 + HTTP/1.1.  Keep the
        # fallback secure while avoiding an unnecessary browser handoff or
        # plaintext HTTP downgrade.
        "--ipv4",
        "--http1.1",
        "--location",
        "--silent",
        "--show-error",
        "--connect-timeout",
        f"{timeout:g}",
        "--max-time",
        f"{timeout:g}",
        "--user-agent",
        BROWSER_HEADERS["User-Agent"],
        "--header",
        f"Accept-Language: {BROWSER_HEADERS['Accept-Language']}",
    ]
    if temporary.exists() and temporary.stat().st_size > 0:
        command.extend(["--continue-at", "-"])
    command.extend(
        [
            "--output",
            str(temporary),
            "--write-out",
            f"{marker}%{{http_code}}\t%{{content_type}}\t%{{url_effective}}",
            url,
        ]
    )
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout + 2,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"curl exit code {completed.returncode}"
        raise ConnectionError(detail)

    metadata = completed.stdout.rpartition(marker)[2]
    fields = metadata.split("\t", 2)
    if len(fields) != 3:
        raise OSError("curl did not return download metadata")
    status_text, content_type, final_url = fields
    status = int(status_text)
    if status == 429 or status >= 500:
        raise ConnectionError(f"HTTP {status}")
    if status >= 400:
        raise ValueError(f"HTTP {status}")
    return final_url, content_type, temporary.stat().st_size


def should_retry(error: BaseException) -> bool:
    if isinstance(error, HTTPError):
        return error.code == 429 or error.code >= 500
    return isinstance(
        error,
        (
            URLError,
            HTTPException,
            socket.timeout,
            TimeoutError,
            ConnectionError,
            subprocess.TimeoutExpired,
        ),
    )


def prepare_partial(output: Path, url: str) -> tuple[Path, Path]:
    """Reuse a partial only when it belongs to the same requested URL."""
    temporary = output.parent / f".{output.name}.part"
    metadata = output.parent / f".{output.name}.part.url"
    recorded_url = ""
    if metadata.exists():
        recorded_url = metadata.read_text(encoding="utf-8", errors="replace").strip()
    if temporary.exists() and temporary.stat().st_size > 0 and recorded_url == url:
        return temporary, metadata
    temporary.unlink(missing_ok=True)
    metadata.unlink(missing_ok=True)
    with metadata.open("w", encoding="utf-8", newline="\n") as record:
        record.write(f"{url}\n")
    return temporary, metadata


def main() -> int:
    args = parse_args()
    if args.timeout <= 0 or args.timeout > 60:
        raise SystemExit("--timeout must be greater than 0 and no more than 60")

    output = args.output.expanduser().resolve(strict=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        download_lock = acquire_download_lock(output)
    except (OSError, RuntimeError) as error:
        print(f"Download failed: {error}", file=sys.stderr)
        return 1

    try:
        temporary, partial_metadata = prepare_partial(output, args.url)
        attempts = args.retries + 1
        preserve_partial = False

        try:
            for attempt in range(1, attempts + 1):
                try:
                    resume_available = temporary.exists() and temporary.stat().st_size > 0
                    if (attempt > 1 or resume_available) and shutil.which("curl") is not None:
                        curl_timeout = effective_download_timeout(
                            args.timeout, output.suffix.lower()
                        )
                        final_url, content_type, total = download_with_curl(
                            args.url, temporary, curl_timeout
                        )
                    else:
                        final_url, content_type, total = download_once(
                            args.url,
                            temporary,
                            args.timeout,
                            output.suffix.lower(),
                        )
                    validate_download(
                        temporary,
                        output.suffix.lower(),
                        content_type,
                        allow_split_component=args.split_component,
                    )
                    os.replace(temporary, output)
                    partial_metadata.unlink(missing_ok=True)
                    print(f"output={output.as_posix()}")
                    print(f"bytes={total}")
                    print(f"content_type={content_type}")
                    print(f"final_url={final_url}")
                    return 0
                except (
                    HTTPError,
                    URLError,
                    HTTPException,
                    socket.timeout,
                    TimeoutError,
                    ConnectionError,
                    subprocess.TimeoutExpired,
                    OSError,
                    ValueError,
                ) as error:
                    retriable = should_retry(error)
                    if attempt >= attempts or not retriable:
                        preserve_partial = bool(
                            retriable
                            and temporary.exists()
                            and temporary.stat().st_size > 0
                        )
                        print(f"Download failed: {error}", file=sys.stderr)
                        if preserve_partial:
                            print(f"partial={temporary.as_posix()}", file=sys.stderr)
                            print(
                                f"partial_bytes={temporary.stat().st_size}",
                                file=sys.stderr,
                            )
                        return 1
            return 1
        finally:
            if not preserve_partial:
                temporary.unlink(missing_ok=True)
                partial_metadata.unlink(missing_ok=True)
    finally:
        release_download_lock(download_lock)


if __name__ == "__main__":
    raise SystemExit(main())
