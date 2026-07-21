from __future__ import annotations

import sys
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from extract_download_link import analyze_html  # noqa: E402


class AnalyzeHtmlTests(unittest.TestCase):
    def test_passive_recaptcha_asset_does_not_block_signed_link(self) -> None:
        html = """
        <style>.grecaptcha-badge { display: none; }</style>
        <script src="https://www.google.com/recaptcha/api.js"></script>
        <a class="variant" href="/r2?u=https%3A%2F%2Ffiles.example%2Fapp.apks">
          App 1.2.3 XAPK
        </a>
        """
        result = analyze_html(
            html,
            "https://apkcombo.com/app/pkg/download/apk",
            expected_package=None,
            expected_version="1.2.3",
        )
        self.assertEqual(result.classification, "download_link")
        self.assertFalse(result.visible_captcha)
        self.assertEqual(
            result.links,
            [
                "https://apkcombo.com/r2?u="
                "https%3A%2F%2Ffiles.example%2Fapp.apks"
            ],
        )

    def test_visible_captcha_without_link_is_blocking(self) -> None:
        html = """
        <p>Verify you are human to continue.</p>
        <div class="g-recaptcha"></div>
        """
        result = analyze_html(html, "https://example.com/download")
        self.assertEqual(result.classification, "captcha_required")
        self.assertTrue(result.visible_captcha)

    def test_package_mismatch_stops_before_link_selection(self) -> None:
        html = '<a class="variant" href="/r2?u=wrong">Wrong app</a>'
        result = analyze_html(
            html,
            "https://example.com/download",
            expected_package="com.expected.app",
        )
        self.assertEqual(result.classification, "package_mismatch")
        self.assertEqual(result.links, [])

    def test_apkcombo_loading_error_requires_browser_instead_of_no_link(self) -> None:
        html = """
        <html><body>
          com.mwp.vendengineapp.cp version 3.6.1
          <p>Downloading. Just a sec…</p>
          <p>Sorry, something went wrong.</p>
          <button>Retry</button>
        </body></html>
        """
        result = analyze_html(
            html,
            "https://apkcombo.com/correctpay/com.mwp.vendengineapp.cp/download/apk",
            expected_package="com.mwp.vendengineapp.cp",
            expected_version="3.6.1",
        )
        self.assertEqual(result.classification, "browser_required")
        self.assertEqual(result.links, [])
        self.assertFalse(result.visible_captcha)

    def test_uptodown_exact_page_404_requires_browser(self) -> None:
        result = analyze_html(
            "not found",
            "https://toctoc-live-video-chat.en.uptodown.com/android",
            status=404,
            expected_package="com.toctoc.video.live.chat",
            expected_version="1.1.6268",
        )
        self.assertEqual(result.classification, "browser_required")
        self.assertEqual(result.links, [])

    def test_apkpure_public_file_link_is_extracted(self) -> None:
        html = """
        com.toctoc.video.live.chat 1.1.6268
        <a href="https://d.apkpure.net/b/APK/com.toctoc.video.live.chat?version=latest">
          Download APK
        </a>
        """
        result = analyze_html(
            html,
            "https://apkpure.net/toctoc-live-video-chat/com.toctoc.video.live.chat/download",
            expected_package="com.toctoc.video.live.chat",
            expected_version="1.1.6268",
        )
        self.assertEqual(result.classification, "download_link")
        self.assertEqual(
            result.links,
            ["https://d.apkpure.net/b/APK/com.toctoc.video.live.chat?version=latest"],
        )

    def test_apkpure_detail_without_file_anchor_requires_browser(self) -> None:
        html = """
        <html><body>
          <h1>Fanova for Creators</h1>
          <p>com.fanovaapp.fanovaapp</p>
          <p>Latest Version 1.0.2</p>
          <button>Download APK</button>
        </body></html>
        """
        result = analyze_html(
            html,
            "https://apkpure.com/cn/fanova-for-creators/com.fanovaapp.fanovaapp",
            expected_package="com.fanovaapp.fanovaapp",
            expected_version="1.0.2",
        )
        self.assertEqual(result.classification, "browser_required")
        self.assertEqual(result.links, [])


if __name__ == "__main__":
    unittest.main()
