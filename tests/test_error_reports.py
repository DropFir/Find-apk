from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from lan_share.error_reports import (
    clean_error_filename,
    clean_error_reason,
    ErrorApkStore,
)


class ErrorApkStoreTests(unittest.TestCase):
    def test_cleans_zip_filename_and_reason(self) -> None:
        self.assertEqual(
            clean_error_filename("../Problem Package.zip"),
            "Problem Package.zip",
        )
        self.assertEqual(
            clean_error_reason("  ARM64 分包缺失\r\n无法安装  "),
            "ARM64 分包缺失\n无法安装",
        )

        with self.assertRaises(ValueError):
            clean_error_filename("problem.apk")
        with self.assertRaises(ValueError):
            clean_error_reason("   ")

    def test_adds_lists_and_resolves_uploaded_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ErrorApkStore(
                root / "error-apks.sqlite3",
                root / "files",
            )
            store.initialize()
            stored_name = "stored.zip"
            (store.files_root / stored_name).write_bytes(b"PK-test")

            report = store.add(
                original_name="problem.zip",
                stored_name=stored_name,
                reason="安装失败",
                size=7,
            )

            self.assertEqual(store.count(), 1)
            self.assertEqual(store.list()[0].id, report.id)
            resolved = store.resolve_file(report.id)
            self.assertIsNotNone(resolved)
            self.assertEqual(resolved[0], store.files_root / stored_name)
            self.assertEqual(resolved[1], "problem.zip")

    def test_missing_uploaded_file_is_not_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ErrorApkStore(
                root / "error-apks.sqlite3",
                root / "files",
            )
            store.initialize()
            report = store.add(
                original_name="missing.zip",
                stored_name="missing.zip",
                reason="文件缺失",
                size=100,
            )

            self.assertIsNone(store.resolve_file(report.id))


if __name__ == "__main__":
    unittest.main()
