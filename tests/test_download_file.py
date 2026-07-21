from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from download_file import validate_download  # noqa: E402


class RetryHandler(BaseHTTPRequestHandler):
    payload = b"PK\x03\x04" + (b"find-apk-test" * 128)
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


if __name__ == "__main__":
    unittest.main()
