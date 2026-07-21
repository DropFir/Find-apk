from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"


class PackagePageHandler(BaseHTTPRequestHandler):
    payload = b"PK\x03\x04" + (b"resolved-package" * 64)

    def do_GET(self) -> None:
        if self.path == "/download/apk":
            body = b"""
                <html><body>
                com.example.app version 1.2.3
                <a class="variant" href="/file.xapk">Download</a>
                </body></html>
            """
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/file.xapk":
            self.send_response(200)
            self.send_header("Content-Type", "application/xapk-package-archive")
            self.send_header("Content-Length", str(len(self.payload)))
            self.end_headers()
            self.wfile.write(self.payload)
            return
        self.send_error(404)

    def log_message(self, format: str, *args: object) -> None:
        pass


class DownloadFromPageTests(unittest.TestCase):
    def test_resolves_and_downloads_in_one_command(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), PackagePageHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "example_1.2.3.xapk"
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(TOOLS_DIR / "download_from_page.py"),
                        f"http://127.0.0.1:{server.server_port}/download/apk",
                        str(output),
                        "--package-name",
                        "com.example.app",
                        "--version",
                        "1.2.3",
                        "--page-timeout",
                        "5",
                        "--download-timeout",
                        "5",
                        "--retries",
                        "0",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertIn("classification=download_link", completed.stdout)
                self.assertIn("pipeline_result=saved", completed.stdout)
                self.assertEqual(output.read_bytes(), PackagePageHandler.payload)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
