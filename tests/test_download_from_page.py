from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from download_from_page import (  # noqa: E402
    apkmirror_final_download_url,
    apkmirror_intermediate_page_url,
    apkpure_download_page_url,
    resolve_download_page,
)
from extract_download_link import PageResult  # noqa: E402


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
    def test_apkmirror_page_automatically_resolves_final_download_endpoint(self) -> None:
        package = "com.sirius"
        detail_url = (
            "https://www.apkmirror.com/apk/sirius/siriusxm/"
            "siriusxm-7-27-1-release/siriusxm-7-27-1-android-apk-download/"
        )
        intermediate_url = f"{detail_url}download/?key=detail-key"
        final_url = (
            "https://www.apkmirror.com/wp-content/themes/APKMirror/"
            "download.php?id=123&key=file-key"
        )
        pages = {
            detail_url: PageResult(
                200,
                detail_url,
                "text/html",
                f'<html>{package} 7.27.1 <a href="{intermediate_url}">Download APK</a></html>',
            ),
            intermediate_url: PageResult(
                200,
                intermediate_url,
                "text/html",
                f'<html>{package} 7.27.1 <a href="{final_url}">Download APK</a></html>',
            ),
        }

        with patch("download_from_page.fetch_page", side_effect=lambda url, timeout: pages[url]) as mocked:
            page, analysis, transition = resolve_download_page(
                detail_url,
                package,
                "7.27.1",
                20,
            )

        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(transition, intermediate_url)
        self.assertEqual(page.final_url, intermediate_url)
        self.assertEqual(analysis.classification, "download_link")
        self.assertEqual(analysis.links, [final_url])

    def test_apkmirror_link_helpers_ignore_unrelated_links(self) -> None:
        detail_url = "https://www.apkmirror.com/apk/example/app/app-download/"
        body = '<a href="/search/?q=app">Search</a>'
        self.assertIsNone(apkmirror_intermediate_page_url(body, detail_url))
        self.assertIsNone(apkmirror_final_download_url(body, detail_url))

    def test_apkpure_detail_automatically_transitions_to_download_page(self) -> None:
        package = "myinstants.meme.soundboard.sound.effects.soundbuttons"
        detail_url = f"https://apkpure.com/myinstants-sound-buttons/{package}"
        download_url = f"{detail_url}/download"
        direct_url = f"https://d.apkpure.com/b/XAPK/{package}?version=latest"
        pages = {
            detail_url: PageResult(
                200,
                detail_url,
                "text/html",
                f"<html>{package} 1.0.17 <button>Download XAPK</button></html>",
            ),
            download_url: PageResult(
                200,
                download_url,
                "text/html",
                f'<html>{package} 1.0.17 <a href="{direct_url}">Download XAPK</a></html>',
            ),
        }

        with patch("download_from_page.fetch_page", side_effect=lambda url, timeout: pages[url]) as mocked:
            page, analysis, transition = resolve_download_page(
                detail_url,
                package,
                "1.0.17",
                20,
            )

        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(transition, download_url)
        self.assertEqual(page.final_url, download_url)
        self.assertEqual(analysis.classification, "download_link")
        self.assertEqual(analysis.links, [direct_url])

    def test_apkpure_download_page_is_not_transitioned_twice(self) -> None:
        package = "com.example.app"
        self.assertIsNone(
            apkpure_download_page_url(
                f"https://apkpure.com/example/{package}/download",
                package,
            )
        )

    def test_reference_version_does_not_reject_newer_apkpure_page(self) -> None:
        package = "com.pinger.textfree.call"
        detail_url = f"https://apkpure.com/text-free/{package}"
        download_url = f"{detail_url}/download"
        direct_url = f"https://d.apkpure.com/b/XAPK/{package}?version=latest"
        pages = {
            detail_url: PageResult(
                200,
                detail_url,
                "text/html",
                f'<script>window.app={{"versionName":"13.22"}}</script>{package}',
            ),
            download_url: PageResult(
                200,
                download_url,
                "text/html",
                f'<script>window.app={{"versionName":"13.22"}}</script>{package}'
                f'<a href="{direct_url}">Download XAPK</a>',
            ),
        }

        with patch("download_from_page.fetch_page", side_effect=lambda url, timeout: pages[url]):
            page, analysis, transition = resolve_download_page(
                detail_url,
                package,
                "13.21",
                20,
            )

        self.assertEqual(transition, download_url)
        self.assertEqual(page.final_url, download_url)
        self.assertEqual(analysis.classification, "download_link")
        self.assertEqual(analysis.detected_version, "13.22")
        self.assertEqual(analysis.links, [direct_url])

    def test_apkpure_transition_failure_keeps_detail_page_version(self) -> None:
        package = "com.pinger.textfree.call"
        detail_url = f"https://apkpure.com/text-free/{package}"
        download_url = f"{detail_url}/download"
        pages = {
            detail_url: PageResult(
                200,
                detail_url,
                "text/html",
                f'<script>window.app={{"versionName":"13.22"}}</script>{package}',
            ),
            download_url: PageResult(410, download_url, "text/html", "gone"),
        }

        with patch("download_from_page.fetch_page", side_effect=lambda url, timeout: pages[url]):
            page, analysis, transition = resolve_download_page(
                detail_url,
                package,
                "13.21",
                20,
            )

        self.assertEqual(transition, download_url)
        self.assertEqual(page.final_url, download_url)
        self.assertEqual(analysis.classification, "gone")
        self.assertEqual(analysis.detected_version, "13.22")

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
