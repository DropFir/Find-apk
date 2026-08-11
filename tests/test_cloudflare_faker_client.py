from __future__ import annotations

import fcntl
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import MagicMock, patch


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from cloudflare_faker_client import (  # noqa: E402
    CloudflareFakerError,
    download_package_with_browser,
    fetch_rendered_html,
)


class CloudflareFakerClientTests(unittest.TestCase):
    @staticmethod
    def response_with_html(html: str) -> MagicMock:
        response = MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.read.return_value = json.dumps(
            {"type": "object", "data": {"html": html}}
        ).encode()
        return response

    def test_uses_unique_fragment_without_changing_http_target(self) -> None:
        response = MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.read.return_value = json.dumps(
            {"type": "object", "data": {"html": "<html>ok</html>"}}
        ).encode()

        with patch("cloudflare_faker_client.urlopen", return_value=response) as mocked:
            with tempfile.TemporaryDirectory() as temporary_directory:
                lock_path = Path(temporary_directory) / "faker.lock"
                with (
                    patch("cloudflare_faker_client.FAKER_LOCK_PATH", lock_path),
                    patch("cloudflare_faker_client.close_faker_tab") as close_tab,
                ):
                    html = fetch_rendered_html("https://example.com/app?q=1", 45)

        request = mocked.call_args.args[0]
        payload = json.loads(request.data.decode())
        self.assertEqual(html, "<html>ok</html>")
        self.assertRegex(
            payload["pageUrl"],
            r"^https://example\.com/app\?q=1#_findapk_faker=[0-9a-f]{32}$",
        )
        close_tab.assert_called_once()
        self.assertRegex(close_tab.call_args.args[0], r"^_findapk_faker=[0-9a-f]{32}$")

    def test_preserves_extension_error_detail(self) -> None:
        response = MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.read.return_value = json.dumps(
            {
                "error": {
                    "type": "TAB_LOAD_TIMEOUT",
                    "message": "New tab failed to load within timeout",
                }
            }
        ).encode()

        with tempfile.TemporaryDirectory() as temporary_directory:
            lock_path = Path(temporary_directory) / "faker.lock"
            with (
                patch("cloudflare_faker_client.urlopen", return_value=response),
                patch("cloudflare_faker_client.FAKER_LOCK_PATH", lock_path),
                patch("cloudflare_faker_client.close_faker_tab") as close_tab,
            ):
                with self.assertRaisesRegex(
                    CloudflareFakerError,
                    "New tab failed to load within timeout",
                ):
                    fetch_rendered_html("https://example.com/app", 45)
            close_tab.assert_called_once()

    def test_reuses_tab_until_cloudflare_challenge_clears(self) -> None:
        challenge = self.response_with_html(
            "<html><title>请稍候…</title><div id='cf-chl-widget'></div></html>"
        )
        application = self.response_with_html(
            "<html><title>Buzz PRO</title></html>"
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            lock_path = Path(temporary_directory) / "faker.lock"
            with (
                patch(
                    "cloudflare_faker_client.urlopen",
                    side_effect=[challenge, application],
                ) as mocked,
                patch("cloudflare_faker_client.FAKER_LOCK_PATH", lock_path),
                patch("cloudflare_faker_client.close_faker_tab") as close_tab,
                patch("cloudflare_faker_client.time.sleep") as sleep,
            ):
                html = fetch_rendered_html("https://example.com/app", 45)

        self.assertIn("Buzz PRO", html)
        self.assertEqual(mocked.call_count, 2)
        first_payload = json.loads(mocked.call_args_list[0].args[0].data.decode())
        second_payload = json.loads(mocked.call_args_list[1].args[0].data.decode())
        self.assertEqual(first_payload["pageUrl"], second_payload["pageUrl"])
        sleep.assert_called_once()
        close_tab.assert_called_once()

    def test_busy_extension_is_not_called_concurrently(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            lock_path = Path(temporary_directory) / "faker.lock"
            with lock_path.open("a+") as blocker:
                fcntl.flock(blocker.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                with (
                    patch("cloudflare_faker_client.FAKER_LOCK_PATH", lock_path),
                    patch("cloudflare_faker_client.urlopen") as mocked,
                    patch("cloudflare_faker_client.close_faker_tab") as close_tab,
                ):
                    with self.assertRaisesRegex(
                        CloudflareFakerError,
                        "request queue timed out",
                    ):
                        fetch_rendered_html("https://example.com/app", 0.1)
                    mocked.assert_not_called()
                    close_tab.assert_not_called()

    def test_browser_download_returns_completed_local_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            downloaded = root / "Buzz-PRO.xapk"
            downloaded.write_bytes(b"PK\x03\x04test")
            response = MagicMock()
            response.__enter__.return_value = response
            response.__exit__.return_value = False
            response.read.return_value = json.dumps(
                {
                    "type": "object",
                    "data": {
                        "path": str(downloaded),
                        "url": "https://cdn.example/Buzz-PRO.xapk",
                        "bytes": downloaded.stat().st_size,
                    },
                }
            ).encode()
            lock_path = root / "faker.lock"
            with (
                patch("cloudflare_faker_client.urlopen", return_value=response) as mocked,
                patch("cloudflare_faker_client.FAKER_LOCK_PATH", lock_path),
                patch("cloudflare_faker_client.close_faker_tab") as close_tab,
            ):
                path, final_url, byte_count = download_package_with_browser(
                    "https://apkpure.com/app/package/download",
                    "https://d.apkpure.com/b/XAPK/app.package?version=latest",
                    900,
                )

        payload = json.loads(mocked.call_args.args[0].data.decode())
        self.assertEqual(path.name, "Buzz-PRO.xapk")
        self.assertEqual(final_url, "https://cdn.example/Buzz-PRO.xapk")
        self.assertEqual(byte_count, 8)
        self.assertEqual(payload["script"], "https://d.apkpure.com/b/XAPK/app.package?version=latest")
        self.assertEqual(payload["pageUrl"], "https://apkpure.com/app/package/download")
        self.assertEqual(payload["entryPageUrl"], "https://apkpure.com/app/package")
        close_tab.assert_not_called()


if __name__ == "__main__":
    unittest.main()
