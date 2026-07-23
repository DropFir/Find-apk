from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from download_file import validate_download  # noqa: E402
from download_split_archive import (  # noqa: E402
    component_filename,
    normalize_components,
    write_xapk,
)


def package_bytes(entries: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return output.getvalue()


class DownloadSplitArchiveTests(unittest.TestCase):
    def test_accepts_expected_mi9_component_url(self) -> None:
        url = (
            "https://downloads.androidcontents.com/com.example.app/"
            "?token=abc&filename=config.arm64_v8a.apk"
        )
        self.assertEqual(
            component_filename(url, "com.example.app"),
            "config.arm64_v8a.apk",
        )

    def test_rejects_unrelated_host_or_package(self) -> None:
        with self.assertRaisesRegex(ValueError, "allowed HTTPS"):
            component_filename(
                "https://files.example.com/com.example.app/?filename=base.apk",
                "com.example.app",
            )
        with self.assertRaisesRegex(ValueError, "expected package"):
            component_filename(
                "https://downloads.androidcontents.com/com.other.app/"
                "?filename=base.apk",
                "com.example.app",
            )

    def test_requires_base_and_split(self) -> None:
        base_url = (
            "https://downloads.androidcontents.com/com.example.app/"
            "?filename=com_example_app_v1.apk"
        )
        with self.assertRaisesRegex(ValueError, "at least one base"):
            normalize_components([base_url], "com.example.app")

    def test_builds_manifested_valid_xapk_from_visible_components(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "com_example_app_v1.apk"
            base.write_bytes(
                package_bytes(
                    {
                        "AndroidManifest.xml": b"manifest",
                        "classes.dex": b"com/unity3d/player/UnityPlayer",
                        "res/xml/splits0.xml": b"config.arm64_v8a",
                    }
                )
            )
            abi = root / "config.arm64_v8a.apk"
            abi.write_bytes(
                package_bytes(
                    {
                        "AndroidManifest.xml": b"manifest",
                        "lib/arm64-v8a/libgame.so": b"native",
                    }
                )
            )
            language = root / "config.en.apk"
            language.write_bytes(
                package_bytes(
                    {
                        "AndroidManifest.xml": b"manifest",
                        "resources.arsc": b"language",
                    }
                )
            )
            output = root / "example_1.0.xapk"

            write_xapk(
                [base, abi, language],
                output,
                package_name="com.example.app",
                app_name="Example",
                version="1.0",
            )

            validate_download(output, ".xapk", "application/octet-stream")
            with zipfile.ZipFile(output) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                self.assertEqual(
                    set(archive.namelist()),
                    {
                        "com.example.app.apk",
                        "config.arm64_v8a.apk",
                        "config.en.apk",
                        "manifest.json",
                    },
                )
            self.assertEqual(manifest["package_name"], "com.example.app")
            self.assertEqual(manifest["version_name"], "1.0")
            self.assertEqual(
                manifest["split_configs"],
                ["config.arm64_v8a", "config.en"],
            )
            self.assertEqual(
                manifest["split_apks"][0],
                {"file": "com.example.app.apk", "id": "base"},
            )


if __name__ == "__main__":
    unittest.main()
