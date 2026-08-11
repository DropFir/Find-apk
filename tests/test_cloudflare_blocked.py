from __future__ import annotations

import unittest

from lan_share.app import candidate_package_name, parse_open_graph_image


class CloudflareBlockedTests(unittest.TestCase):
    def test_extracts_package_name_from_supported_candidate_paths(self) -> None:
        self.assertEqual(
            candidate_package_name(
                "https://apkpure.com/example/com.example.mobile/download"
            ),
            "com.example.mobile",
        )
        self.assertEqual(
            candidate_package_name(
                "https://apkcombo.com/example/com.example.combo/download/apk"
            ),
            "com.example.combo",
        )
        self.assertEqual(
            candidate_package_name("https://example.en.uptodown.com/android"),
            "",
        )

    def test_extracts_open_graph_icon_regardless_of_attribute_order(self) -> None:
        page = (
            '<html><head><meta content="https://play-lh.googleusercontent.com/icon" '
            'property="og:image"></head></html>'
        )
        self.assertEqual(
            parse_open_graph_image(page),
            "https://play-lh.googleusercontent.com/icon",
        )


if __name__ == "__main__":
    unittest.main()
