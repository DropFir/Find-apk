from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from lan_share.external_monitor import ExternalProductionMonitor
from lan_share.production_queue import ProductionQueue


class FakeExternalMonitor(ExternalProductionMonitor):
    def _fetch_date(self, selected_date: str) -> list[dict[str, object]]:
        return [
            {
                "id": "external-1",
                "display_name": (
                    "Example_App_com.example.app_" + selected_date
                ),
                "package_name": "com.example.app",
                "state": "queued_step2",
            }
        ]

    def _refresh_public_packages(self) -> None:
        return


class FakePublicMonitor(ExternalProductionMonitor):
    def _fetch_date(self, selected_date: str) -> list[dict[str, object]]:
        return []

    @staticmethod
    def _fetch_text(url: str) -> str:
        return """<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url>
            <loc>https://www.apkba.com/example-app/com.example.app</loc>
          </url>
        </urlset>
        """


class ExternalProductionMonitorTests(unittest.TestCase):
    def test_exact_package_match_marks_the_queue_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = ProductionQueue(Path(temporary) / "production.sqlite3")
            queue.initialize()
            delivery = {
                "id": 1,
                "delivery_key": "2026-07-27/example:signature",
                "directory": "2026-07-27/example",
                "signature": "signature",
                "keyword": "Example App",
                "date": "2026-07-27",
                "application_id": "com.example.app",
            }
            monitor = FakeExternalMonitor(
                "http://192.168.5.125:8088/",
                initial_lookback_days=1,
            )

            self.assertEqual(monitor.check([delivery], queue), 1)
            self.assertEqual(monitor.check([delivery], queue), 0)
            snapshot = queue.sync_and_list([delivery])
            item = next(
                item
                for lane in snapshot["lanes"].values()
                for item in lane
            )
            self.assertEqual(item["queue_status"], "external_completed")
            self.assertEqual(
                item["external_package"],
                "com.example.app",
            )

    def test_public_sitemap_marks_exact_package_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = ProductionQueue(Path(temporary) / "production.sqlite3")
            queue.initialize()
            delivery = {
                "id": 1,
                "delivery_key": "2026-07-27/example:signature",
                "directory": "2026-07-27/example",
                "signature": "signature",
                "keyword": "Example App",
                "date": "2026-07-27",
                "application_id": "com.example.app",
            }
            monitor = FakePublicMonitor(
                "http://192.168.5.125:8088/",
                initial_lookback_days=1,
            )

            self.assertEqual(monitor.check([delivery], queue), 1)
            status = monitor.status()
            self.assertEqual(status["public_packages"], 1)
            self.assertIsNone(status["last_public_error"])


if __name__ == "__main__":
    unittest.main()
