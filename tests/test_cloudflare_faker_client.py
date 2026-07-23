from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from cloudflare_faker_client import (  # noqa: E402
    CloudflareFakerError,
    fetch_rendered_html,
)


class CloudflareFakerClientTests(unittest.TestCase):
    def test_uses_unique_fragment_without_changing_http_target(self) -> None:
        response = MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.read.return_value = json.dumps(
            {"type": "object", "data": {"html": "<html>ok</html>"}}
        ).encode()

        with patch("cloudflare_faker_client.urlopen", return_value=response) as mocked:
            html = fetch_rendered_html("https://example.com/app?q=1", 45)

        request = mocked.call_args.args[0]
        payload = json.loads(request.data.decode())
        self.assertEqual(html, "<html>ok</html>")
        self.assertRegex(
            payload["pageUrl"],
            r"^https://example\.com/app\?q=1#_findapk_faker=[0-9a-f]{32}$",
        )

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

        with patch("cloudflare_faker_client.urlopen", return_value=response):
            with self.assertRaisesRegex(
                CloudflareFakerError,
                "New tab failed to load within timeout",
            ):
                fetch_rendered_html("https://example.com/app", 45)


if __name__ == "__main__":
    unittest.main()
