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

    def test_uptodown_store_installer_data_url_is_not_a_package_candidate(self) -> None:
        html = """
        <html><body>
          <p>com.flightradar24free</p><p>Version 11.7.0</p>
          <button data-url="/android/download-with-uptodown-app-store">
            Download with Uptodown App Store
          </button>
          <button class="button variants">All variants</button>
        </body></html>
        """
        result = analyze_html(
            html,
            "https://flightradar24.en.uptodown.com/android/download",
            expected_package="com.flightradar24free",
            expected_version="11.7.0",
        )
        self.assertEqual(result.classification, "browser_required")
        self.assertEqual(result.links, [])

    def test_androidapks_direct_package_link_is_extracted(self) -> None:
        direct_url = (
            "https://r-static-assets.androidapksfree.net/rdata/example/"
            "com.offerup_v4.45.0.apk"
        )
        html = f"""
        <html><body>
          <p>com.offerup</p><p>Version 4.45.0</p>
          <a href="{direct_url}">Download APK</a>
        </body></html>
        """
        result = analyze_html(
            html,
            "https://androidapks.com/offerup/com-offerup/download/",
            expected_package="com.offerup",
            expected_version="4.45.0",
        )
        self.assertEqual(result.classification, "download_link")
        self.assertEqual(result.links, [direct_url])

    def test_softonic_uses_target_download_and_ignores_helper(self) -> None:
        target_url = (
            "https://en.softonic.com/download/ai-grammar-checker-for-english/"
            "android/post-download?dt=internalDownload"
        )
        helper_url = (
            "https://en.softonic.com/download/softonic-helper/"
            "android/post-download?dt=internalDownload"
        )
        html = f"""
        <html><body>
          <p>com.hellotalk.aigrammar</p><p>Version 1.6.25</p>
          <a href="{helper_url}">Download with Softonic Helper</a>
          <a href="{target_url}">Free XAPK Download for Android</a>
        </body></html>
        """
        result = analyze_html(
            html,
            "https://ai-grammar-checker-for-english.en.softonic.com/android/download",
            expected_package="com.hellotalk.aigrammar",
            expected_version="1.6.25",
        )
        self.assertEqual(result.classification, "download_link")
        self.assertEqual(result.links, [target_url])

    def test_softonic_client_challenge_requires_browser(self) -> None:
        result = analyze_html(
            "<html><title>Client Challenge</title></html>",
            "https://ai-grammar-checker-for-english.en.softonic.com/android",
            expected_package="com.hellotalk.aigrammar",
            expected_version="1.6.25",
        )
        self.assertEqual(result.classification, "browser_required")

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

    def test_apkpure_promotional_client_link_is_filtered(self) -> None:
        package = "com.je.supersus"
        requested = f"https://d.apkpure.com/b/XAPK/{package}?version=latest"
        html = f"""
        {package} 1.80.6.031
        <a href="{requested}">Download XAPK</a>
        <a href="https://d.apkpure.com/custom/com.apkpure.aegon-3207737.apk">
          Install APKPure
        </a>
        """
        result = analyze_html(
            html,
            f"https://apkpure.com/super-sus/{package}/download",
            expected_package=package,
            expected_version="1.80.6.031",
        )
        self.assertEqual(result.classification, "download_link")
        self.assertEqual(result.links, [requested])

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

    def test_newer_page_version_is_accepted_by_default(self) -> None:
        html = """
        <script>window.app = {"versionName":"13.22"};</script>
        <p>com.pinger.textfree.call</p>
        <button>Download APK</button>
        """
        result = analyze_html(
            html,
            "https://apkpure.com/text-free/com.pinger.textfree.call",
            expected_package="com.pinger.textfree.call",
            expected_version="13.21",
        )
        self.assertEqual(result.classification, "browser_required")
        self.assertEqual(result.detected_version, "13.22")

    def test_older_page_version_is_accepted_when_latest_is_unavailable(self) -> None:
        html = """
        <script>window.app = {"versionName":"13.13.1"};</script>
        <p>com.pinger.textfree.call</p>
        <a class="variant" href="/r2?u=older-package">Download</a>
        """
        result = analyze_html(
            html,
            "https://apkcombo.com/text-free/com.pinger.textfree.call/download/apk",
            expected_package="com.pinger.textfree.call",
            expected_version="13.21",
        )
        self.assertEqual(result.classification, "download_link")
        self.assertEqual(result.detected_version, "13.13.1")

    def test_explicit_version_remains_strict(self) -> None:
        html = """
        <script>window.app = {"versionName":"13.22"};</script>
        <p>com.pinger.textfree.call</p>
        <a class="variant" href="/r2?u=newer-package">Download</a>
        """
        result = analyze_html(
            html,
            "https://apkcombo.com/text-free/com.pinger.textfree.call/download/apk",
            expected_package="com.pinger.textfree.call",
            expected_version="13.21",
            version_policy="exact",
        )
        self.assertEqual(result.classification, "version_mismatch")
        self.assertEqual(result.detected_version, "13.22")


if __name__ == "__main__":
    unittest.main()
