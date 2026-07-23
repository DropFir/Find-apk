from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from download_file import (  # noqa: E402
    acquire_download_lock,
    effective_download_timeout,
    release_download_lock,
    validate_download,
)


def package_bytes(entries: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return output.getvalue()


class RetryHandler(BaseHTTPRequestHandler):
    payload = package_bytes(
        {
            "AndroidManifest.xml": b"manifest",
            "classes.dex": b"pure-java-test",
        }
    )
    request_count = 0
    resumed_from = None

    def do_GET(self) -> None:
        type(self).request_count += 1
        range_header = self.headers.get("Range")
        if range_header == "bytes=32-":
            type(self).resumed_from = 32
            remainder = self.payload[32:]
            self.send_response(206)
            self.send_header("Content-Type", "application/vnd.android.package-archive")
            self.send_header("Content-Length", str(len(remainder)))
            self.send_header(
                "Content-Range", f"bytes 32-{len(self.payload) - 1}/{len(self.payload)}"
            )
            self.end_headers()
            self.wfile.write(remainder)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.android.package-archive")
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()
        if type(self).request_count == 1:
            self.wfile.write(self.payload[:32])
            self.wfile.flush()
            self.close_connection = True
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        self.wfile.write(self.payload)

    def log_message(self, format: str, *args: object) -> None:
        pass


class DownloadFileTests(unittest.TestCase):
    def test_target_lock_rejects_concurrent_writer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "same-target.xapk"
            lock = acquire_download_lock(output)
            try:
                with self.assertRaisesRegex(RuntimeError, "another download"):
                    acquire_download_lock(output)
            finally:
                release_download_lock(lock)

            second_lock = acquire_download_lock(output)
            release_download_lock(second_lock)

    def test_large_package_timeout_scales_with_file_size(self) -> None:
        self.assertEqual(
            effective_download_timeout(20, ".xapk", 50 * 1024 * 1024),
            100,
        )
        self.assertEqual(
            effective_download_timeout(20, ".xapk", 907_673_197),
            900,
        )

    def test_preserves_partial_and_resumes_on_next_command(self) -> None:
        RetryHandler.request_count = 0
        RetryHandler.resumed_from = None
        server = ThreadingHTTPServer(("127.0.0.1", 0), RetryHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "sample.apk"
                command = [
                    sys.executable,
                    str(TOOLS_DIR / "download_file.py"),
                    f"http://127.0.0.1:{server.server_port}/sample.apk",
                    str(output),
                    "--timeout",
                    "5",
                    "--retries",
                    "0",
                ]

                first = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                partial = output.parent / f".{output.name}.part"
                metadata = output.parent / f".{output.name}.part.url"
                self.assertEqual(first.returncode, 1)
                self.assertEqual(partial.stat().st_size, 32)
                self.assertTrue(metadata.exists())

                second = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                self.assertEqual(second.returncode, 0, second.stderr)
                self.assertEqual(output.read_bytes(), RetryHandler.payload)
                self.assertEqual(RetryHandler.resumed_from, 32)
                self.assertFalse(partial.exists())
                self.assertFalse(metadata.exists())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_retries_truncated_response_with_curl(self) -> None:
        RetryHandler.request_count = 0
        RetryHandler.resumed_from = None
        server = ThreadingHTTPServer(("127.0.0.1", 0), RetryHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "sample.apk"
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(TOOLS_DIR / "download_file.py"),
                        f"http://127.0.0.1:{server.server_port}/sample.apk",
                        str(output),
                        "--timeout",
                        "5",
                        "--retries",
                        "1",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(output.read_bytes(), RetryHandler.payload)
                self.assertEqual(RetryHandler.request_count, 2)
                self.assertEqual(RetryHandler.resumed_from, 32)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_rejects_html_saved_with_apk_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "fake.apk"
            output.write_text("<!doctype html><title>blocked</title>", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "returned HTML"):
                validate_download(output, ".apk", "text/html; charset=utf-8")

    def test_rejects_native_game_engine_base_apk_without_abi_split(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "base.apk"
            output.write_bytes(
                package_bytes(
                    {
                        "AndroidManifest.xml": b"manifest",
                        "classes.dex": (
                            b"com/unity3d/player/UnityPlayer\x00"
                            b"com/google/android/play/core/splitcompat"
                        ),
                        "res/xml/splits0.xml": b"config.arm64_v8a",
                    }
                )
            )

            with self.assertRaisesRegex(ValueError, "missing its required ABI split"):
                validate_download(
                    output,
                    ".apk",
                    "application/vnd.android.package-archive",
                )

    def test_accepts_valid_base_apk_as_explicit_split_component(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "base.apk"
            output.write_bytes(
                package_bytes(
                    {
                        "AndroidManifest.xml": b"manifest",
                        "classes.dex": b"com/unity3d/player/UnityPlayer",
                        "res/xml/splits0.xml": b"config.arm64_v8a",
                    }
                )
            )

            validate_download(
                output,
                ".apk",
                "application/vnd.android.package-archive",
                allow_split_component=True,
            )

    def test_accepts_native_game_engine_apk_when_library_is_embedded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "universal.apk"
            output.write_bytes(
                package_bytes(
                    {
                        "AndroidManifest.xml": b"manifest",
                        "classes.dex": b"cocos2dcpp",
                        "res/xml/splits0.xml": b"config.en",
                        "lib/arm64-v8a/libcocos2dcpp.so": b"native-library",
                    }
                )
            )

            validate_download(
                output,
                ".apk",
                "application/vnd.android.package-archive",
            )

    def test_accepts_pure_java_apk_without_native_libraries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "java.apk"
            output.write_bytes(
                package_bytes(
                    {
                        "AndroidManifest.xml": b"manifest",
                        "classes.dex": b"pure-java-app",
                        "res/xml/splits0.xml": b"config.en",
                    }
                )
            )

            validate_download(
                output,
                ".apk",
                "application/vnd.android.package-archive",
            )

    def test_accepts_native_split_package_with_abi_library(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "game.xapk"
            base = package_bytes(
                {
                    "AndroidManifest.xml": b"manifest",
                    "classes.dex": b"header cocos2dcpp footer",
                    "res/xml/splits0.xml": b"splits",
                }
            )
            abi = package_bytes(
                {
                    "AndroidManifest.xml": b"manifest",
                    "lib/arm64-v8a/libgame.so": b"native",
                }
            )
            output.write_bytes(
                package_bytes(
                    {
                        "base.apk": base,
                        "config.arm64_v8a.apk": abi,
                    }
                )
            )

            validate_download(output, ".xapk", "application/octet-stream")

    def test_rejects_native_split_package_without_abi_library(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "game.xapk"
            base = package_bytes(
                {
                    "AndroidManifest.xml": b"manifest",
                    "classes.dex": b"header cocos2dcpp footer",
                    "res/xml/splits0.xml": b"splits",
                }
            )
            output.write_bytes(
                package_bytes(
                    {
                        "base.apk": base,
                        "config.en.apk": package_bytes(
                            {
                                "AndroidManifest.xml": b"manifest",
                                "resources.arsc": b"language",
                            }
                        ),
                    }
                )
            )

            with self.assertRaisesRegex(ValueError, "missing a required ABI APK"):
                validate_download(output, ".xapk", "application/octet-stream")

    def test_rejects_split_package_with_bad_outer_crc(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "game.xapk"
            with zipfile.ZipFile(
                output, "w", compression=zipfile.ZIP_STORED
            ) as archive:
                archive.writestr("base.apk", b"unique-payload")
            damaged = output.read_bytes().replace(
                b"unique-payload", b"broken-payload", 1
            )
            output.write_bytes(damaged)

            with self.assertRaisesRegex(ValueError, "ZIP/CRC validation"):
                validate_download(output, ".xapk", "application/octet-stream")


if __name__ == "__main__":
    unittest.main()
