from __future__ import annotations

from pathlib import Path
import sys
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from extract_search_candidates import analyze_search_html  # noqa: E402


class AnalyzeSearchHtmlTests(unittest.TestCase):
    def test_apkpure_search_finds_exact_myinstants_package(self) -> None:
        html = """
        <a href="/myinstants-sound-buttons/myinstants.com.soundboard.soundbuttons.meme.effects.sound">
          Similar MyInstants app
        </a>
        <a href="/myinstants-sound-buttons/myinstants.meme.soundboard.sound.effects.soundbuttons">
          MyInstants: Sound Buttons
        </a>
        """
        result = analyze_search_html(
            html,
            "https://apkpure.com/search?q=MyInstants%3A+Sound+Buttons",
            "https://apkpure.com/search?q=MyInstants%3A+Sound+Buttons",
            200,
            "myinstants.meme.soundboard.sound.effects.soundbuttons",
        )

        self.assertEqual(result.classification, "candidate_found")
        self.assertEqual(
            result.links,
            [
                "https://apkpure.com/myinstants-sound-buttons/"
                "myinstants.meme.soundboard.sound.effects.soundbuttons"
            ],
        )

    def test_generic_search_redirect_is_not_no_candidates(self) -> None:
        result = analyze_search_html(
            "<html><title>Search Hot Android Apps & Games</title></html>",
            "https://apkpure.com/search?q=com.example.app",
            "https://apkpure.com/search",
            200,
            "com.example.app",
        )

        self.assertEqual(result.classification, "generic_search_redirect")
        self.assertEqual(result.links, [])

    def test_complete_page_without_match_is_no_candidates(self) -> None:
        result = analyze_search_html(
            '<a href="/another-app/com.example.other">Another App</a>',
            "https://example.com/search?q=Target",
            "https://example.com/search?q=Target",
            200,
            "com.example.target",
        )

        self.assertEqual(result.classification, "no_candidates")
        self.assertEqual(result.links, [])


if __name__ == "__main__":
    unittest.main()
