from __future__ import annotations

import json
from pathlib import Path
import unittest


class BrowserBlocklistTests(unittest.TestCase):
    def test_playafterdark_is_permanently_blocked(self) -> None:
        config_path = Path(__file__).resolve().parents[1] / "sources.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        policy = config["browserSessionPolicy"]

        self.assertIn("playafterdark.com", policy["blockedDomains"])
        self.assertIn("iccku.com", policy["blockedDomains"])
        self.assertTrue(policy["closeBlockedDomainTabsImmediately"])
        self.assertTrue(policy["neverReadClickOrNavigateBlockedDomains"])


if __name__ == "__main__":
    unittest.main()
