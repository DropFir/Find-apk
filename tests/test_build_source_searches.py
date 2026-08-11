from __future__ import annotations

import json
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

    def test_appends_enabled_public_downloader_for_confirmed_package(self) -> None:
        config = {
            "preferredSources": [],
            "publicDownloaderFallbacks": [
                {
                    "name": "MI9 APK Downloader",
                    "entryUrl": "https://mi9.com/apk-downloader/",
                    "enabled": True,
                }
            ],
        }

        searches = build_searches(config, "Example", "com.example.app")

        self.assertEqual(
            searches,
            [
                {
                    "source": "MI9 APK Downloader",
                    "term_type": "package",
                    "method": "browser_generator",
                    "target": "https://mi9.com/apk-downloader/",
                    "fallback_target": "",
                }
            ],
        )

    def test_apkpure_net_is_a_separate_configured_source(self) -> None:
        config = {
            "preferredSources": [
                {
                    "name": "APKPure",
                    "baseUrl": "https://apkpure.com",
                    "searchUrlTemplate": "https://apkpure.com/search?q={query}",
                    "enabled": True,
                },
                {
                    "name": "APKPure.net",
                    "baseUrl": "https://apkpure.net",
                    "searchUrlTemplate": "https://apkpure.net/search?q={query}",
                    "enabled": True,
                },
            ]
        }

        searches = build_searches(config, "SkyView Lite", "com.t11.skyviewfree")

        self.assertEqual(len(searches), 4)
        self.assertEqual(
            searches[2]["target"],
            "https://apkpure.net/search?q=SkyView+Lite",
        )
        self.assertEqual(
            searches[3]["fallback_target"],
            'site:apkpure.net "com.t11.skyviewfree" APK',
        )

    def test_supports_generic_google_alternative_query(self) -> None:
        config = {
            "preferredSources": [
                {
                    "name": "Google Web Alternatives",
                    "searchMode": "webQuery",
                    "searchQueryTemplate": '"{query}" Android APK download',
                    "enabled": True,
                }
            ]
        }

        searches = build_searches(config, "Example App", "com.example.app")

        self.assertEqual(
            [item["target"] for item in searches],
            [
                '"Example App" Android APK download',
                '"com.example.app" Android APK download',
            ],
        )
        self.assertTrue(
            all(item["method"] == "external_query" for item in searches)
        )

    def test_repository_prioritizes_google_before_cloudflare_prone_sources(
        self,
    ) -> None:
        config_path = Path(__file__).resolve().parents[1] / "sources.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        enabled = [
            source
            for source in config["preferredSources"]
            if source.get("enabled", False)
        ]
        names = [source["name"] for source in enabled]

        self.assertEqual(names[0], "Google Web Alternatives")
        first_blocked_index = min(
            index
            for index, source in enumerate(enabled)
            if source.get("priorityTier") == "cloudflare-last"
        )
        self.assertTrue(
            all(
                source.get("priorityTier") == "cloudflare-last"
                for source in enabled[first_blocked_index:]
            )
        )

    def test_does_not_append_public_downloader_without_confirmed_package(self) -> None:
        config = {
            "preferredSources": [],
            "publicDownloaderFallbacks": [
                {
                    "name": "MI9 APK Downloader",
                    "entryUrl": "https://mi9.com/apk-downloader/",
                    "enabled": True,
                }
            ],
        }

        self.assertEqual(build_searches(config, "Example"), [])


if __name__ == "__main__":
    unittest.main()
