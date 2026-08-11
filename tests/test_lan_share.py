from __future__ import annotations

import io
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image

from lan_share.bundles import (
    HISTORICAL_SOURCE_NOTE,
    create_delivery_bundle,
    remove_delivery_directory,
)
from lan_share.codex_controller import CodexController
from lan_share.indexer import DeliveryIndex, display_name, normalize_search_text
from lan_share.app import (
    production_storage_summary,
    rewrite_apkba_monitor_html,
    storage_status,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = PROJECT_ROOT / "tools" / "validate_delivery.py"


def write_package(path: Path, application_id: str | None = None) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        manifest = (
            f'<manifest package="{application_id}"></manifest>'.encode()
            if application_id
            else b"manifest"
        )
        archive.writestr("AndroidManifest.xml", manifest)
        archive.writestr("classes.dex", b"pure-java-test")


def write_icon(path: Path) -> None:
    image = Image.new("RGBA", (64, 64), (50, 160, 90, 255))
    output = io.BytesIO()
    image.save(output, format="WEBP", lossless=True)
    path.write_bytes(output.getvalue())


class DeliveryIndexTests(unittest.TestCase):
    def make_index(self, root: Path) -> DeliveryIndex:
        index = DeliveryIndex(
            root / "downloads",
            root / "state" / "index.sqlite3",
            VALIDATOR,
        )
        index.initialize()
        return index

    def test_indexes_only_complete_valid_deliveries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            complete = root / "downloads" / "2026-07-25" / "sample-app"
            incomplete = root / "downloads" / "2026-07-25" / "missing-icon"
            complete.mkdir(parents=True)
            incomplete.mkdir(parents=True)

            write_package(complete / "sample-app.apk")
            write_icon(complete / "icon.webp")
            (complete / "developer.txt").write_text(
                "Example Developer\n",
                encoding="utf-8",
            )
            write_package(incomplete / "missing-icon.apk")
            (incomplete / "developer.txt").write_text(
                "Other Developer\n",
                encoding="utf-8",
            )

            index = self.make_index(root)
            self.assertTrue(index.scan())

            items = index.search_json()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["keyword"], "Sample App")
            self.assertEqual(items[0]["developer"], "Example Developer")
            self.assertEqual(items[0]["package_format"], "APK")

    def test_searches_keyword_developer_and_filename(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            delivery = root / "downloads" / "2026-07-25" / "city-weather"
            delivery.mkdir(parents=True)
            write_package(delivery / "forecast-client_3.2.apk")
            write_icon(delivery / "icon.webp")
            (delivery / "developer.txt").write_text(
                "North Wind Labs\n",
                encoding="utf-8",
            )

            index = self.make_index(root)
            index.scan()

            self.assertEqual(len(index.search("city weather")), 1)
            self.assertEqual(len(index.search("cityweather")), 1)
            self.assertEqual(len(index.search("north wind")), 1)
            self.assertEqual(len(index.search("northwind")), 1)
            self.assertEqual(len(index.search("forecast-client")), 1)
            self.assertEqual(index.search("unrelated"), [])

    def test_production_candidates_include_stable_snapshot_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            delivery = root / "downloads" / "2026-07-25" / "daily-app"
            delivery.mkdir(parents=True)
            write_package(
                delivery / "daily-app.apk",
                "com.example.daily",
            )
            write_icon(delivery / "icon.webp")
            (delivery / "developer.txt").write_text(
                "Daily Labs\n",
                encoding="utf-8",
            )

            index = self.make_index(root)
            index.scan()
            candidates = index.production_candidates()

            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["directory"], "2026-07-25/daily-app")
            self.assertTrue(candidates[0]["signature"])
            self.assertEqual(
                candidates[0]["application_id"],
                "com.example.daily",
            )
            self.assertEqual(
                candidates[0]["delivery_key"],
                f"{candidates[0]['directory']}:{candidates[0]['signature']}",
            )
            record = index.resolve_production_record(candidates[0]["id"])
            self.assertIsNotNone(record)
            self.assertEqual(
                record["delivery_key"],
                candidates[0]["delivery_key"],
            )

    def test_incomplete_delivery_appears_after_becoming_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            delivery = root / "downloads" / "2026-07-25" / "later"
            delivery.mkdir(parents=True)
            write_package(delivery / "later.apk")
            (delivery / "developer.txt").write_text(
                "Later Labs\n",
                encoding="utf-8",
            )

            index = self.make_index(root)
            index.scan()
            self.assertEqual(index.search(), [])

            write_icon(delivery / "icon.webp")
            index.scan()
            self.assertEqual(len(index.search()), 1)

    def test_resolve_file_stays_inside_downloads(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            delivery = root / "downloads" / "2026-07-25" / "safe-app"
            delivery.mkdir(parents=True)
            write_package(delivery / "safe.apk")
            write_icon(delivery / "icon.webp")
            (delivery / "developer.txt").write_text(
                "Safe Labs\n",
                encoding="utf-8",
            )

            index = self.make_index(root)
            index.scan()
            delivery_id = index.search()[0].id

            package = index.resolve_file(delivery_id, "package")
            self.assertIsNotNone(package)
            self.assertTrue(package.is_relative_to(index.downloads_root))
            self.assertIsNone(index.resolve_file(delivery_id, "unknown"))

    def test_scan_repairs_stale_stored_icon_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            delivery = root / "downloads" / "2026-07-25" / "repaired-app"
            delivery.mkdir(parents=True)
            write_package(delivery / "repaired.apk")
            write_icon(delivery / "repaired.webp")
            (delivery / "developer.txt").write_text(
                "Repair Labs\n",
                encoding="utf-8",
            )

            index = self.make_index(root)
            index.scan()
            delivery_id = index.search()[0].id
            with sqlite3.connect(index.database_path) as connection:
                connection.execute(
                    """
                    UPDATE deliveries
                    SET icon_relpath = ?
                    WHERE rowid = ?
                    """,
                    (
                        "2026-07-25/repaired-app/.removed-icon.webp",
                        delivery_id,
                    ),
                )

            self.assertIsNone(index.resolve_file(delivery_id, "icon"))
            self.assertTrue(index.scan())
            self.assertEqual(
                index.resolve_file(delivery_id, "icon"),
                (delivery / "repaired.webp").resolve(),
            )

    def test_delivery_bundle_contains_package_icon_developer_and_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            delivery = root / "downloads" / "2026-07-25" / "bundle-app"
            delivery.mkdir(parents=True)
            write_package(delivery / "bundle-app.apk")
            write_icon(delivery / "bundle-app.webp")
            (delivery / "developer.txt").write_text(
                "Bundle Labs\n",
                encoding="utf-8",
            )
            (delivery / "source.txt").write_text(
                "https://example.com/bundle-app\n",
                encoding="utf-8",
            )

            index = self.make_index(root)
            index.scan()
            delivery_id = index.search()[0].id
            files = index.resolve_delivery_files(delivery_id)
            self.assertIsNotNone(files)

            archive_path = create_delivery_bundle(files, root / "state" / "bundles")
            try:
                with zipfile.ZipFile(archive_path) as archive:
                    self.assertEqual(
                        set(archive.namelist()),
                        {
                            "bundle-app.apk",
                            "icon.webp",
                            "developer.txt",
                            "source.txt",
                        },
                    )
                    self.assertEqual(
                        archive.read("developer.txt").decode("utf-8"),
                        "Bundle Labs\n",
                    )
                    self.assertEqual(
                        archive.read("source.txt").decode("utf-8"),
                        "https://example.com/bundle-app\n",
                    )
            finally:
                archive_path.unlink(missing_ok=True)

    def test_delivery_bundle_explains_missing_historical_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            delivery = root / "downloads" / "2026-07-25" / "legacy-app"
            delivery.mkdir(parents=True)
            write_package(delivery / "legacy.apk")
            write_icon(delivery / "legacy.webp")
            (delivery / "developer.txt").write_text(
                "Legacy Labs\n",
                encoding="utf-8",
            )

            index = self.make_index(root)
            index.scan()
            files = index.resolve_delivery_files(index.search()[0].id)
            self.assertIsNotNone(files)

            archive_path = create_delivery_bundle(files, root / "state" / "bundles")
            try:
                with zipfile.ZipFile(archive_path) as archive:
                    self.assertEqual(
                        archive.read("source.txt").decode("utf-8"),
                        HISTORICAL_SOURCE_NOTE,
                    )
            finally:
                archive_path.unlink(missing_ok=True)

    def test_remove_delivery_directory_deletes_only_selected_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            downloads = root / "downloads"
            selected = downloads / "2026-07-25" / "selected-app"
            retained = downloads / "2026-07-25" / "retained-app"
            selected.mkdir(parents=True)
            retained.mkdir(parents=True)
            (selected / "selected.apk").write_bytes(b"selected")
            (retained / "retained.apk").write_bytes(b"retained")

            self.assertTrue(remove_delivery_directory(selected, downloads))
            self.assertFalse(selected.exists())
            self.assertTrue(retained.is_dir())

    def test_remove_delivery_directory_refuses_unsafe_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            downloads = root / "downloads"
            outside = root / "outside"
            downloads.mkdir()
            outside.mkdir()

            with self.assertRaises(ValueError):
                remove_delivery_directory(downloads, downloads)
            with self.assertRaises(ValueError):
                remove_delivery_directory(outside, downloads)

    def test_search_normalization_handles_punctuation(self) -> None:
        self.assertEqual(
            normalize_search_text("Sam's Club—Shopping"),
            "sam s club shopping",
        )

    def test_display_name_reuses_developer_brand_casing(self) -> None:
        self.assertEqual(display_name("spothero", "SpotHero, Inc."), "SpotHero")
        self.assertEqual(display_name("duke-energy", "Duke Energy"), "Duke Energy")

    def test_apkba_embed_uses_local_summary_proxy(self) -> None:
        original = (
            b"<script>fetch('/api/summary?date='+"
            b"encodeURIComponent('2026-07-29'))</script>"
        )
        rewritten = rewrite_apkba_monitor_html(original)

        self.assertIn("fetch('/api/apkba-summary?date='", rewritten)
        self.assertNotIn("fetch('/api/summary?date='", rewritten)

    def test_storage_status_reports_capacity_and_percentage(self) -> None:
        with patch(
            "lan_share.app.shutil.disk_usage",
            return_value=SimpleNamespace(total=1000, used=750, free=250),
        ):
            status = storage_status(Path("/downloads"))

        self.assertEqual(status["total"], 1000)
        self.assertEqual(status["used"], 750)
        self.assertEqual(status["free"], 250)
        self.assertEqual(status["percent"], 75.0)

    def test_production_storage_summary_counts_only_existing_deliveries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            downloads = root / "downloads"
            delivery = downloads / "2026-08-08" / "kept"
            delivery.mkdir(parents=True)
            (delivery / "package.apk").write_bytes(b"a" * 128)
            bundles = root / "bundles"
            bundles.mkdir()
            (bundles / "find-apk-delivery-test.zip").write_bytes(b"b" * 64)

            summary = production_storage_summary(
                [
                    {"directory": "2026-08-08/kept"},
                    {"directory": "2026-08-08/missing"},
                ],
                downloads_root=downloads,
                bundles_root=bundles,
            )

        self.assertEqual(summary["directories"], 1)
        self.assertEqual(summary["bytes"], 128)
        self.assertEqual(summary["temporary_files"], 1)
        self.assertEqual(summary["temporary_bytes"], 64)

    def test_codex_controller_persists_bounded_schedule_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller = CodexController(root, root / "state" / "codex.json")
            snapshot = controller.configure(
                {
                    "enabled": True,
                    "model": "gpt-5.6-terra",
                    "effort": "medium",
                    "interval_minutes": 30,
                    "batch_size": 5,
                    "workers": 2,
                }
            )
            restored = CodexController(root, root / "state" / "codex.json")

        self.assertTrue(snapshot["settings"]["enabled"])
        self.assertIsNotNone(snapshot["next_run_at"])
        self.assertEqual(restored.settings.model, "gpt-5.6-terra")
        self.assertEqual(restored.settings.batch_size, 5)

    def test_codex_controller_starts_followup_outside_reader_thread(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller = CodexController(root, root / "state" / "codex.json")
            worker = controller.workers["lan-codex-1"]
            worker.status = "running"
            worker.thread_id = "thread-1"
            worker.turn_id = "turn-1"
            controller._batch_remaining = 1
            started = threading.Event()
            caller: list[threading.Thread] = []
            actions: list[str] = []

            def record_archive(thread_id, _worker) -> bool:
                self.assertEqual(thread_id, "thread-1")
                actions.append("archive")
                return True

            def record_start(_worker) -> bool:
                actions.append("start")
                caller.append(threading.current_thread())
                started.set()
                return True

            with patch.object(
                controller, "_archive_thread", side_effect=record_archive
            ), patch.object(
                controller, "_start_next_worker", side_effect=record_start
            ):
                reader_thread = threading.current_thread()
                controller._handle_event(
                    {
                        "method": "turn/completed",
                        "params": {"turn": {"id": "turn-1", "status": "completed"}},
                    }
                )
                self.assertTrue(started.wait(1))

        self.assertIsNot(caller[0], reader_thread)
        self.assertEqual(actions, ["archive", "start"])

    def test_codex_controller_archives_and_forgets_finished_thread(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller = CodexController(root, root / "state" / "codex.json")
            worker = controller.workers["lan-codex-1"]
            worker.thread_id = "thread-complete"
            requests: list[tuple[str, dict[str, str], float]] = []

            def record_request(method, params, timeout=30):
                requests.append((method, params, timeout))
                return {}

            with patch.object(controller, "_request", side_effect=record_request):
                archived = controller._archive_thread(worker.thread_id, worker)

        self.assertTrue(archived)
        self.assertIsNone(worker.thread_id)
        self.assertEqual(
            requests,
            [("thread/archive", {"threadId": "thread-complete"}, 30)],
        )

    def test_codex_controller_retries_error_workers_on_next_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller = CodexController(root, root / "state" / "codex.json")
            controller.settings.workers = 1
            worker = controller.workers["lan-codex-1"]
            worker.status = "error"
            worker.thread_id = "stale-thread"
            observed: list[tuple[str, object]] = []

            def record_start(selected_worker) -> bool:
                observed.append((selected_worker.status, selected_worker.thread_id))
                return True

            with patch.object(
                controller,
                "_start_next_worker",
                side_effect=record_start,
            ):
                result = controller.run_now()

        self.assertEqual(result["started"], 1)
        self.assertEqual(observed, [("idle", None)])

    def test_codex_controller_falls_back_after_model_capacity_message(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller = CodexController(root, root / "state" / "codex.json")
            worker = controller.workers["lan-codex-1"]
            worker.status = "running"
            worker.thread_id = "thread-1"
            worker.turn_id = "turn-1"
            worker.active_model = "gpt-5.6-luna"
            worker.stream = [
                "进度：Selected model is at capacity. Please try a different model."
            ]
            controller._batch_remaining = 3
            retried = threading.Event()
            profiles: list[tuple[str | None, str | None]] = []

            def record_retry(
                _worker,
                *,
                model_override=None,
                effort_override=None,
            ) -> bool:
                profiles.append((model_override, effort_override))
                retried.set()
                return True

            with patch.object(
                controller,
                "_start_worker",
                side_effect=record_retry,
            ):
                controller._handle_event(
                    {
                        "method": "turn/completed",
                        "params": {"turn": {"id": "turn-1", "status": "completed"}},
                    }
                )
                self.assertTrue(retried.wait(1))

        self.assertEqual(profiles, [("gpt-5.6-sol", "low")])
        self.assertEqual(controller._batch_remaining, 3)

    def test_codex_controller_uses_terra_medium_when_sol_is_full(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller = CodexController(root, root / "state" / "codex.json")
            worker = controller.workers["lan-codex-1"]
            worker.status = "running"
            worker.thread_id = "thread-sol"
            worker.turn_id = "turn-sol"
            worker.active_model = "gpt-5.6-sol"
            worker.active_effort = "low"
            worker.stream = ["进度：Selected model is at capacity."]
            retried = threading.Event()
            profiles: list[tuple[str | None, str | None]] = []

            def record_retry(
                _worker,
                *,
                model_override=None,
                effort_override=None,
            ) -> bool:
                profiles.append((model_override, effort_override))
                retried.set()
                return True

            with patch.object(
                controller,
                "_start_worker",
                side_effect=record_retry,
            ):
                controller._handle_event(
                    {
                        "method": "turn/completed",
                        "params": {"turn": {"id": "turn-sol", "status": "completed"}},
                    }
                )
                self.assertTrue(retried.wait(1))

        self.assertEqual(profiles, [("gpt-5.6-terra", "medium")])


if __name__ == "__main__":
    unittest.main()
