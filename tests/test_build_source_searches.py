from __future__ import annotations

from pathlib import Path
import sys
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from build_source_searches import build_searches  # noqa: E402


class BuildSourceSearchesTests(unittest.TestCase):
    def test_includes_every_enabled_source_and_encodes_terms(self) -> None:
        config = {
            "preferredSources": [
                {
                    "name": "APKPure",
                    "baseUrl": "https://apkpure.com",
                    "searchUrlTemplate": "https://apkpure.com/search?q={query}",
                    "enabled": True,
                },
                {
                    "name": "CNET",
                    "baseUrl": "https://download.cnet.com",
                    "searchMode": "externalSiteQuery",
                    "enabled": True,
                },
                {
                    "name": "Disabled",
                    "baseUrl": "https://example.com",
                    "enabled": False,
                },
            ]
        }

        searches = build_searches(config, "Pink Pink", "com.example.pink")

        self.assertEqual(len(searches), 4)
        self.assertEqual(
            searches[0]["target"], "https://apkpure.com/search?q=Pink+Pink"
        )
        self.assertEqual(
            searches[1]["target"], "https://apkpure.com/search?q=com.example.pink"
        )
        self.assertEqual(
            searches[1]["fallback_target"],
            'site:apkpure.com "com.example.pink" APK',
        )
        self.assertEqual(
            searches[2]["target"], 'site:download.cnet.com "Pink Pink" APK'
        )
        self.assertEqual({item["source"] for item in searches}, {"APKPure", "CNET"})


if __name__ == "__main__":
    unittest.main()
