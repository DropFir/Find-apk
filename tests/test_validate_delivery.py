from __future__ import annotations

import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from PIL import Image


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"


def write_package(path: Path) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("AndroidManifest.xml", b"manifest")
        archive.writestr("classes.dex", b"pure-java-test")


def write_icon(path: Path) -> None:
    image = Image.new("RGBA", (64, 64), (10, 20, 30, 255))
    output = io.BytesIO()
    image.save(output, format="WEBP", lossless=True)
    path.write_bytes(output.getvalue())


def run_validator(directory: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOLS_DIR / "validate_delivery.py"), str(directory)],
        check=False,
        capture_output=True,
        text=True,
    )


class ValidateDeliveryTests(unittest.TestCase):
    def test_accepts_complete_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_package(directory / "sample.apk")
            write_icon(directory / "icon.webp")
            (directory / "developer.txt").write_text("Example Developer\n")

            completed = run_validator(directory)

            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertIn("classification=valid_delivery", completed.stdout)

    def test_rejects_missing_icon(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_package(directory / "sample.apk")
            (directory / "developer.txt").write_text("Example Developer\n")

            completed = run_validator(directory)

            self.assertEqual(completed.returncode, 1)
            self.assertIn("no valid WEBP icon", completed.stdout)

    def test_rejects_multiline_developer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_package(directory / "sample.apk")
            write_icon(directory / "icon.webp")
            (directory / "developer.txt").write_text("One\nTwo\n")

            completed = run_validator(directory)

            self.assertEqual(completed.returncode, 1)
            self.assertIn("exactly one non-empty line", completed.stdout)


if __name__ == "__main__":
    unittest.main()
