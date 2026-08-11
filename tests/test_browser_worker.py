from __future__ import annotations

from pathlib import Path
import tempfile
import time
import unittest

from lan_share.browser_worker import (
    BrowserDownloadStore,
    BrowserDownloadWorker,
    BrowserWorkerError,
    PersistentChromeBackend,
    entry_page_url,
    package_suffix,
)


class FakeBrowserBackend:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.chrome_port = 9223
        self.profile_path = root / "profile"
        self.browser = object()
        self.downloaded: list[int] = []
        self.closed = False
        self.reset_count = 0

    def ensure_browser(self):
        self.profile_path.mkdir(parents=True, exist_ok=True)
        return self.browser

    def download(self, task, work_directory, update):
        self.downloaded.append(task.id)
        update(status="verifying", detail="正在等待测试页面")
        update(
            status="downloading",
            detail="正在下载测试文件",
            progress=50,
            received_bytes=5,
            total_bytes=10,
        )
        work_directory.mkdir(parents=True, exist_ok=True)
        package = work_directory / f"package-{task.id}{task.suffix}"
        package.write_bytes(b"PK\x03\x04package")
        return package, task.download_url, package.stat().st_size

    def close(self):
        self.closed = True

    def reset_to_idle_page(self):
        self.reset_count += 1


def wait_for_task(store: BrowserDownloadStore, task_id: int, timeout: float = 3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = store.get(task_id)
        if task and task.status in {"completed", "failed"}:
            return task
        time.sleep(0.02)
    raise AssertionError("browser task did not finish")


class BrowserWorkerTests(unittest.TestCase):
    def test_derives_detail_page_and_package_suffix(self) -> None:
        self.assertEqual(
            entry_page_url("https://apkpure.com/cn/app/pkg/download"),
            "https://apkpure.com/cn/app/pkg",
        )
        self.assertEqual(
            package_suffix("https://d.apkpure.com/b/XAPK/pkg?version=latest"),
            ".xapk",
        )

    def test_worker_processes_submissions_serially_and_reports_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = BrowserDownloadStore(root / "browser.sqlite3")
            store.initialize()
            backend = FakeBrowserBackend(root)
            worker = BrowserDownloadWorker(store, backend, root / "jobs")
            worker.start()
            try:
                first = store.submit(
                    "https://apkpure.com/app/pkg/download",
                    "https://d.apkpure.com/b/XAPK/pkg?version=latest",
                )
                second = store.submit(
                    "https://apkpure.com/app/other/download",
                    "https://d.apkpure.com/b/APK/other?version=latest",
                )
                first_result = wait_for_task(store, first.id)
                second_result = wait_for_task(store, second.id)
                snapshot = store.snapshot()
            finally:
                worker.stop()

            self.assertEqual(first_result.status, "completed")
            self.assertEqual(second_result.status, "completed")
            self.assertEqual(backend.downloaded, [first.id, second.id])
            self.assertTrue(Path(first_result.result_path).is_file())
            self.assertEqual(snapshot["counts"]["completed"], 2)
            self.assertEqual(backend.reset_count, 2)
            self.assertTrue(backend.closed)

    def test_initialize_recovers_interrupted_task_only_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = BrowserDownloadStore(Path(temporary) / "browser.sqlite3")
            store.initialize()
            task = store.submit(
                "https://apkpure.com/app/pkg/download",
                "https://d.apkpure.com/b/XAPK/pkg?version=latest",
            )
            store.update(task.id, status="downloading", detail="下载中")
            store.initialize(recover=False)
            self.assertEqual(store.get(task.id).status, "downloading")
            store.initialize(recover=True)
            self.assertEqual(store.get(task.id).status, "pending")

    def test_cloudflare_timeout_has_actionable_error(self) -> None:
        class ChallengeTab:
            title = "请稍候…"
            url = "https://apkpure.com/cdn-cgi/challenge"

            @staticmethod
            def ele(_locator, timeout=0):
                return None

        updates = []
        with self.assertRaisesRegex(BrowserWorkerError, "Cloudflare 验证未完成"):
            PersistentChromeBackend._wait_exact_link(
                ChallengeTab(),
                "https://d.apkpure.com/b/XAPK/pkg?version=latest",
                timeout=0.01,
                update=lambda **values: updates.append(values),
            )
        self.assertEqual(
            updates[-1]["detail"],
            "请在专用 Chrome 完成一次 Cloudflare 验证",
        )


if __name__ == "__main__":
    unittest.main()
