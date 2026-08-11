from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from lan_share.production_queue import ProductionQueue


def delivery(
    number: int,
    *,
    signature: str | None = None,
    delivery_date: str | None = None,
    keyword: str | None = None,
    application_id: str | None = None,
) -> dict[str, object]:
    directory = f"2026-07-27/app-{number}"
    resolved_signature = signature or f"signature-{number}"
    return {
        "id": number,
        "delivery_key": f"{directory}:{resolved_signature}",
        "directory": directory,
        "signature": resolved_signature,
        "keyword": keyword or f"App {number}",
        "application_id": application_id,
        "date": delivery_date or "2026-07-27",
    }


class ProductionQueueTests(unittest.TestCase):
    def make_queue(self, root: Path) -> ProductionQueue:
        queue = ProductionQueue(root / "production.sqlite3")
        queue.initialize()
        return queue

    def test_assigns_stable_balanced_lanes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            deliveries = [delivery(number) for number in range(1, 6)]

            first = queue.sync_and_list(deliveries, work_date="2026-07-27")
            second = queue.sync_and_list(
                list(reversed(deliveries)),
                work_date="2026-07-27",
            )

            self.assertEqual(first["counts"], {"1": 3, "2": 2})
            first_lanes = {
                item["delivery_key"]: item["lane"]
                for lane in first["lanes"].values()
                for item in lane
            }
            second_lanes = {
                item["delivery_key"]: item["lane"]
                for lane in second["lanes"].values()
                for item in lane
            }
            self.assertEqual(first_lanes, second_lanes)

    def test_downloaded_item_is_gray_today_and_hidden_tomorrow(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            deliveries = [delivery(1), delivery(2)]
            today = queue.sync_and_list(deliveries, work_date="2026-07-27")
            key = today["lanes"]["1"][0]["delivery_key"]

            self.assertTrue(
                queue.mark_downloaded(key, work_date="2026-07-27")
            )
            refreshed = queue.sync_and_list(
                [
                    delivery(
                        1,
                        signature="new-signature",
                    ),
                    delivery(2),
                ],
                work_date="2026-07-27",
            )
            downloaded = [
                item
                for lane in refreshed["lanes"].values()
                for item in lane
                if item["delivery_key"] == key
            ]
            self.assertEqual(len(downloaded), 1)
            self.assertTrue(downloaded[0]["downloaded"])
            self.assertEqual(refreshed["downloaded"], 1)

            tomorrow = queue.sync_and_list(
                deliveries,
                work_date="2026-07-28",
            )
            tomorrow_keys = {
                item["delivery_key"]
                for lane in tomorrow["lanes"].values()
                for item in lane
            }
            self.assertNotIn(key, tomorrow_keys)
            self.assertEqual(tomorrow["total"], 1)
            remaining = next(
                item
                for lane in tomorrow["lanes"].values()
                for item in lane
            )
            self.assertEqual(remaining["work_date"], "2026-07-28")
            self.assertFalse(remaining["downloaded"])

    def test_new_signature_creates_a_new_daily_item(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            old = delivery(1, signature="old")
            first = queue.sync_and_list([old], work_date="2026-07-27")
            old_key = first["lanes"]["1"][0]["delivery_key"]
            queue.mark_downloaded(old_key, work_date="2026-07-27")

            updated = delivery(1, signature="new")
            tomorrow = queue.sync_and_list(
                [updated],
                work_date="2026-07-28",
            )

            self.assertEqual(tomorrow["total"], 1)
            item = next(
                item
                for lane in tomorrow["lanes"].values()
                for item in lane
            )
            self.assertEqual(item["delivery_key"], updated["delivery_key"])
            self.assertFalse(item["downloaded"])

    def test_removes_active_item_when_delivery_files_disappear(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            missing = delivery(1)
            remaining = delivery(2)
            queue.sync_and_list(
                [missing, remaining],
                work_date="2026-07-27",
            )

            refreshed = queue.sync_and_list(
                [remaining],
                work_date="2026-07-27",
            )

            self.assertEqual(refreshed["total"], 1)
            visible_keys = {
                item["delivery_key"]
                for lane in refreshed["lanes"].values()
                for item in lane
            }
            self.assertEqual(visible_keys, {remaining["delivery_key"]})

    def test_keeps_only_newest_delivery_for_same_application_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            old = delivery(
                1,
                delivery_date="2026-07-26",
                application_id="com.example.same",
            )
            newest = delivery(
                2,
                delivery_date="2026-07-27",
                application_id="com.example.same",
            )

            snapshot = queue.sync_and_list(
                [old, newest],
                work_date="2026-07-27",
            )

            self.assertEqual(snapshot["total"], 1)
            item = next(
                item
                for lane in snapshot["lanes"].values()
                for item in lane
            )
            self.assertEqual(item["delivery_key"], newest["delivery_key"])

    def test_lists_each_lane_for_an_independent_date(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            deliveries = [delivery(1), delivery(2), delivery(3)]
            first = queue.sync_and_list(
                deliveries,
                work_date="2026-07-27",
            )
            downloaded_key = first["lanes"]["1"][0]["delivery_key"]
            queue.mark_downloaded(
                downloaded_key,
                work_date="2026-07-27",
            )

            snapshot = queue.sync_and_list(
                deliveries,
                work_date="2026-07-28",
                lane_dates={
                    1: "2026-07-27",
                    2: "2026-07-28",
                },
            )

            self.assertEqual(
                snapshot["lane_dates"],
                {"1": "2026-07-27", "2": "2026-07-28"},
            )
            self.assertEqual(len(snapshot["lanes"]["1"]), 2)
            self.assertEqual(len(snapshot["lanes"]["2"]), 1)
            self.assertEqual(snapshot["yesterday"]["total"], 3)
            self.assertEqual(
                snapshot["yesterday"]["counts"],
                {"1": 2, "2": 1},
            )
            rolled = snapshot["lanes"]["2"][0]
            self.assertEqual(rolled["queue_status"], "active")

            historical = queue.sync_and_list(
                deliveries,
                work_date="2026-07-28",
                lane_dates={
                    1: "2026-07-27",
                    2: "2026-07-27",
                },
            )
            statuses = {
                item["queue_status"]
                for lane in historical["lanes"].values()
                for item in lane
            }
            self.assertEqual(statuses, {"downloaded", "rolled"})

    def test_backfills_each_day_from_delivery_date(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            deliveries = [
                delivery(1, delivery_date="2026-07-25"),
                delivery(2, delivery_date="2026-07-26"),
            ]

            snapshot = queue.sync_and_list(
                deliveries,
                work_date="2026-07-27",
                lane_dates={
                    1: "2026-07-26",
                    2: "2026-07-26",
                },
            )

            self.assertEqual(snapshot["yesterday"]["total"], 2)
            self.assertEqual(snapshot["total"], 2)
            self.assertEqual(
                {
                    item["queue_status"]
                    for lane in snapshot["lanes"].values()
                    for item in lane
                },
                {"rolled"},
            )

    def test_excluded_delivery_disappears_without_deleting_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            queue = self.make_queue(root)
            deliveries = [delivery(1), delivery(2)]
            initial = queue.sync_and_list(
                deliveries,
                work_date="2026-07-27",
            )
            excluded = initial["lanes"]["1"][0]

            result = queue.exclude_deliveries(
                [
                    {
                        "delivery_key": excluded["delivery_key"],
                        "keyword": excluded["keyword"],
                        "matched_name": excluded["keyword"],
                        "matched_package": "com.example.one",
                        "match_type": "package",
                    }
                ],
                source_url="http://192.168.5.125:8088/",
            )
            refreshed = queue.sync_and_list(
                deliveries,
                work_date="2026-07-27",
            )

            self.assertEqual(result["created"], 1)
            self.assertEqual(refreshed["total"], 1)
            visible_keys = {
                item["delivery_key"]
                for lane in refreshed["lanes"].values()
                for item in lane
            }
            self.assertNotIn(excluded["delivery_key"], visible_keys)
            self.assertTrue((root / "production.sqlite3").is_file())

    def test_exclusion_expands_to_older_snapshots_of_same_keyword(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            deliveries = [
                delivery(1, keyword="Same App"),
                delivery(2, keyword="Same App"),
                delivery(3),
            ]
            initial = queue.sync_and_list(
                deliveries,
                work_date="2026-07-27",
            )
            match = next(
                item
                for lane in initial["lanes"].values()
                for item in lane
                if item["keyword"] == "Same App"
            )

            result = queue.exclude_deliveries(
                [
                    {
                        "delivery_key": match["delivery_key"],
                        "keyword": match["keyword"],
                        "matched_name": match["keyword"],
                        "matched_package": "com.example.same",
                        "match_type": "package",
                    }
                ],
                source_url="http://192.168.5.125:8088/",
            )
            refreshed = queue.sync_and_list(
                deliveries,
                work_date="2026-07-27",
            )

            self.assertEqual(result["created"], 2)
            self.assertEqual(refreshed["total"], 1)

    def test_external_completion_is_visible_today_and_absent_tomorrow(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            deliveries = [delivery(1)]
            initial = queue.sync_and_list(
                deliveries,
                work_date="2026-07-27",
            )
            item = initial["lanes"]["1"][0]

            self.assertTrue(
                queue.mark_external_completed(
                    item["delivery_key"],
                    keyword=item["keyword"],
                    source_url="http://192.168.5.125:8088/",
                    matched_name="App 1",
                    matched_package="com.example.one",
                    work_date="2026-07-27",
                )
            )
            self.assertFalse(
                queue.mark_external_completed(
                    item["delivery_key"],
                    keyword=item["keyword"],
                    source_url="http://192.168.5.125:8088/",
                    matched_name="App 1",
                    matched_package="com.example.one",
                    work_date="2026-07-27",
                )
            )
            today = queue.sync_and_list(
                deliveries,
                work_date="2026-07-27",
            )
            completed = today["lanes"]["1"][0]
            self.assertEqual(
                completed["queue_status"],
                "external_completed",
            )
            self.assertTrue(completed["downloaded"])

            tomorrow = queue.sync_and_list(
                deliveries,
                work_date="2026-07-28",
            )
            self.assertEqual(tomorrow["total"], 0)

    def test_removes_only_locally_downloaded_safe_deliveries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            local = delivery(1)
            external = delivery(2)
            initial = queue.sync_and_list(
                [local, external],
                work_date="2026-07-27",
            )
            items = {
                item["delivery_key"]: item
                for lane in initial["lanes"].values()
                for item in lane
            }
            self.assertTrue(
                queue.mark_downloaded(
                    local["delivery_key"],
                    work_date="2026-07-27",
                )
            )
            self.assertTrue(
                queue.mark_external_completed(
                    external["delivery_key"],
                    keyword=items[external["delivery_key"]]["keyword"],
                    source_url="http://192.168.5.125:8088/",
                    matched_name="App 2",
                    matched_package="com.example.two",
                    work_date="2026-07-27",
                )
            )

            candidates = queue.downloaded_removal_candidates()
            self.assertEqual(
                [item["delivery_key"] for item in candidates],
                [local["delivery_key"]],
            )
            self.assertEqual(queue.record_removed_downloads(candidates), 1)

            refreshed = queue.sync_and_list(
                [local, external],
                work_date="2026-07-27",
            )
            visible_keys = {
                item["delivery_key"]
                for lane in refreshed["lanes"].values()
                for item in lane
            }
            self.assertNotIn(local["delivery_key"], visible_keys)
            self.assertIn(external["delivery_key"], visible_keys)
            self.assertEqual(queue.downloaded_removal_candidates(), [])

    def test_does_not_remove_downloaded_directory_with_active_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            old = delivery(1, signature="old")
            queue.sync_and_list([old], work_date="2026-07-27")
            queue.mark_downloaded(
                old["delivery_key"],
                work_date="2026-07-27",
            )
            current = delivery(1, signature="current")
            queue.sync_and_list([current], work_date="2026-07-27")

            self.assertEqual(queue.downloaded_removal_candidates(), [])


if __name__ == "__main__":
    unittest.main()
