from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import re
import zipfile

from tools.download_file import _parse_binary_manifest_attributes


PACKAGE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+$")
PACKAGE_KEYS = (
    "package_name",
    "packageName",
    "package",
    "applicationId",
    "pname",
)


def package_from_manifest(manifest: bytes) -> str | None:
    elements = _parse_binary_manifest_attributes(manifest)
    if not elements and manifest.lstrip().startswith(b"<"):
        import xml.etree.ElementTree as ElementTree

        root = ElementTree.fromstring(manifest)
        value = root.attrib.get("package")
        return value if value and PACKAGE_PATTERN.fullmatch(value) else None
    for tag, attributes in elements:
        if tag != "manifest":
            continue
        value = attributes.get("package")
        if isinstance(value, str) and PACKAGE_PATTERN.fullmatch(value):
            return value
    return None


def package_from_json(value: object) -> str | None:
    if isinstance(value, dict):
        for key in PACKAGE_KEYS:
            candidate = value.get(key)
            if (
                isinstance(candidate, str)
                and PACKAGE_PATTERN.fullmatch(candidate)
            ):
                return candidate
        for nested in value.values():
            candidate = package_from_json(nested)
            if candidate:
                return candidate
    elif isinstance(value, list):
        for nested in value:
            candidate = package_from_json(nested)
            if candidate:
                return candidate
    return None


def package_from_apk(archive: zipfile.ZipFile) -> str | None:
    try:
        return package_from_manifest(archive.read("AndroidManifest.xml"))
    except (KeyError, ValueError):
        return None


def identify_package(path: Path) -> str | None:
    try:
        with zipfile.ZipFile(path) as archive:
            if path.suffix.casefold() == ".apk":
                return package_from_apk(archive)
            for name in archive.namelist():
                if not name.casefold().endswith(".json"):
                    continue
                try:
                    info = archive.getinfo(name)
                    if info.file_size > 2 * 1024 * 1024:
                        continue
                    candidate = package_from_json(
                        json.loads(archive.read(name).decode("utf-8"))
                    )
                except (KeyError, UnicodeError, json.JSONDecodeError):
                    continue
                if candidate:
                    return candidate
            apk_names = sorted(
                (
                    name
                    for name in archive.namelist()
                    if name.casefold().endswith(".apk")
                ),
                key=lambda name: (
                    0 if Path(name).name.casefold() == "base.apk" else 1,
                    len(name),
                    name,
                ),
            )
            for name in apk_names:
                try:
                    with zipfile.ZipFile(BytesIO(archive.read(name))) as apk:
                        candidate = package_from_apk(apk)
                except (KeyError, OSError, zipfile.BadZipFile):
                    continue
                if candidate:
                    return candidate
    except (OSError, zipfile.BadZipFile):
        return None
    return None
