from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import unittest

from lan_share.queue_store import KeywordQueue, clean_keyword
from tools.keyword_queue import directory_matches_keyword


class KeywordQueueTests(unittest.TestCase):
    def make_queue(self, root: Path) -> KeywordQueue:
        queue = KeywordQueue(root / "state" / "queue.sqlite3")
        queue.initialize()
        return queue

    def test_add_deduplicates_active_keywords(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            first = queue.add(["SpotHero", "  Duke   Energy  ", "spothero"])
            second = queue.add(["SPOTHERO"])

            self.assertEqual(len(first["created"]), 2)
            self.assertEqual(first["created"][1]["keyword"], "Duke Energy")
            self.assertEqual(len(second["created"]), 0)
            self.assertEqual(len(second["existing"]), 1)
            self.assertEqual(queue.snapshot()["counts"]["pending"], 2)

    def test_claim_is_ordered_atomic_and_limited_to_ten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            queue.add([f"App {number:02d}" for number in range(15)])

            claims: list[list[int]] = []

            def claim(worker: str) -> None:
                claims.append(
                    [job.id for job in queue.claim(limit=10, worker=worker)]
                )

            first = threading.Thread(target=claim, args=("worker-one",))
            second = threading.Thread(target=claim, args=("worker-two",))
            first.start()
            second.start()
            first.join()
            second.join()

            flattened = [job_id for group in claims for job_id in group]
            self.assertEqual(len(flattened), 15)
            self.assertEqual(len(set(flattened)), 15)
            self.assertLessEqual(max(len(group) for group in claims), 10)
            self.assertEqual(queue.snapshot()["counts"]["processing"], 15)

    def test_claim_resumes_same_workers_processing_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            queue.add(["One", "Two", "Three"])
            first_claim = queue.claim(limit=2, worker="apk-agent")
            original_claimed_at = first_claim[0].claimed_at

            resumed = queue.claim(limit=10, worker="apk-agent")
            snapshot = queue.snapshot()

            self.assertEqual(
                [job.id for job in resumed],
                [job.id for job in first_claim],
            )
            self.assertEqual([job.attempt_count for job in resumed], [1, 1])
            self.assertGreaterEqual(resumed[0].claimed_at, original_claimed_at)
            self.assertEqual(snapshot["counts"]["processing"], 2)
            self.assertEqual(snapshot["counts"]["pending"], 1)

    def test_claim_does_not_resume_another_workers_processing_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            queue.add(["One", "Two"])
            first_claim = queue.claim(limit=1, worker="worker-one")

            second_claim = queue.claim(limit=1, worker="worker-two")

            self.assertNotEqual(first_claim[0].id, second_claim[0].id)
            self.assertEqual(first_claim[0].claimed_by, "worker-one")
            self.assertEqual(second_claim[0].claimed_by, "worker-two")

    def test_claim_specific_prioritizes_reopened_job(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            queue.add(["Older Pending", "Reopened Target"])
            jobs = queue.claim(limit=2, worker="setup-agent")
            queue.update(jobs[0].id, status="retry", error="retry later")
            queue.record_search_miss(jobs[1].id, reason="complete search chain")
            reopened = queue.reopen(
                jobs[1].id,
                candidate_url="https://example.com/exact-target",
            )

            claimed = queue.claim_specific(
                reopened.id,
                worker="target-agent",
            )

            self.assertEqual(claimed.id, reopened.id)
            self.assertEqual(claimed.status, "processing")
            self.assertEqual(claimed.claimed_by, "target-agent")
            self.assertEqual(
                claimed.candidate_url,
                "https://example.com/exact-target",
            )
            self.assertEqual(
                queue.list_jobs(status="retry")[0].keyword,
                "Older Pending",
            )

    def test_list_jobs_supports_twenty_item_pages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            queue.add([f"Paged App {number:02d}" for number in range(45)])

            first_page = queue.list_jobs(limit=20, offset=0)
            second_page = queue.list_jobs(limit=20, offset=20)
            third_page = queue.list_jobs(limit=20, offset=40)

            self.assertEqual(len(first_page), 20)
            self.assertEqual(len(second_page), 20)
            self.assertEqual(len(third_page), 5)
            self.assertEqual(
                len({job.id for job in first_page + second_page + third_page}),
                45,
            )

    def test_completed_keyword_can_be_added_again(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            job = queue.add(["Acuity"])["created"][0]
            queue.claim(limit=1, worker="agent")
            completed = queue.update(
                job["id"],
                status="completed",
                delivery_directory="downloads/2026-07-25/acuity",
            )
            again = queue.add(["acuity"])

            self.assertEqual(completed.status, "completed")
            self.assertEqual(len(again["created"]), 1)
            self.assertEqual(queue.snapshot()["counts"]["completed"], 1)
            self.assertEqual(queue.snapshot()["counts"]["pending"], 1)

    def test_remove_pending_is_atomic_and_rejects_started_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            jobs = queue.add(["Remove One", "Remove Two", "Keep Processing"])[
                "created"
            ]
            processing = queue.claim_specific(jobs[2]["id"], worker="agent")

            removed = queue.remove_pending([jobs[0]["id"], jobs[1]["id"]])

            self.assertEqual(
                [job.id for job in removed],
                [jobs[0]["id"], jobs[1]["id"]],
            )
            self.assertIsNone(queue.get(jobs[0]["id"]))
            self.assertIsNone(queue.get(jobs[1]["id"]))
            self.assertEqual(queue.get(processing.id).status, "processing")

            replacement = queue.add(["Safe Pending"])["created"][0]
            with self.assertRaisesRegex(ValueError, "cannot be removed"):
                queue.remove_pending([replacement["id"], processing.id])
            self.assertIsNotNone(queue.get(replacement["id"]))
            self.assertIsNotNone(queue.get(processing.id))

    def test_first_complete_search_miss_skips_job(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            job = queue.add(["Web Only App"])["created"][0]
            queue.claim(limit=1, worker="agent")

            missed = queue.record_search_miss(
                job["id"],
                reason="complete identity and source search had no Android package",
            )
            self.assertEqual(missed.status, "not_found_skipped")
            self.assertEqual(missed.search_miss_count, 1)
            self.assertIsNotNone(missed.completed_at)
            snapshot = queue.snapshot()
            self.assertEqual(snapshot["counts"]["processing"], 0)
            self.assertEqual(snapshot["counts"]["not_found_skipped"], 1)

    def test_lists_paid_and_not_found_skips_together(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            queue.add(["Paid App", "Missing App", "Waiting App"])
            jobs = queue.claim(limit=2, worker="agent")
            queue.update(jobs[0].id, status="paid_skipped")
            queue.record_search_miss(jobs[1].id, reason="complete search chain")

            skipped = queue.list_jobs_for_statuses(
                ("paid_skipped", "not_found_skipped")
            )

            self.assertEqual(len(skipped), 2)
            self.assertEqual(
                {job.status for job in skipped},
                {"paid_skipped", "not_found_skipped"},
            )

    def test_searches_skipped_jobs_by_keyword_across_pages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            queue.add(["Family Tree Maker", "Q Interactive", "Paid Family App"])
            jobs = queue.claim(limit=3, worker="agent")
            queue.record_search_miss(jobs[0].id, reason="complete search chain")
            queue.record_search_miss(jobs[1].id, reason="complete search chain")
            queue.update(jobs[2].id, status="paid_skipped")

            matches = queue.list_jobs_for_statuses(
                ("paid_skipped", "not_found_skipped"),
                query="family",
                limit=1,
            )
            total = queue.count_jobs(
                statuses=("paid_skipped", "not_found_skipped"),
                query="family",
            )

            self.assertEqual(len(matches), 1)
            self.assertEqual(total, 2)
            self.assertIn("Family", matches[0].keyword)

    def test_search_miss_requires_processing_job_and_reason(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            job = queue.add(["Queued App"])["created"][0]

            with self.assertRaisesRegex(ValueError, "already pending"):
                queue.record_search_miss(job["id"], reason="no result")

            queue.claim(limit=1, worker="agent")
            with self.assertRaisesRegex(ValueError, "reason is required"):
                queue.record_search_miss(job["id"], reason=" ")

    def test_unresolved_exact_candidate_blocks_search_miss(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            job = queue.add(["Candidate App"])["created"][0]
            queue.claim(limit=1, worker="agent")
            candidate = queue.record_candidate(
                job["id"],
                url="https://apkpure.com/candidate/app.package",
            )

            self.assertEqual(
                candidate.candidate_url,
                "https://apkpure.com/candidate/app.package",
            )
            with self.assertRaisesRegex(ValueError, "exact candidate blocks"):
                queue.record_search_miss(
                    job["id"],
                    reason="download returned Cloudflare 403",
                )

            cleared = queue.clear_candidate(
                job["id"],
                reason="exact page returned verified 410",
            )
            self.assertEqual(cleared.candidate_url, "")
            missed = queue.record_search_miss(
                job["id"],
                reason="all enabled sources had no exact candidate",
            )
            self.assertEqual(missed.search_miss_count, 1)
            self.assertEqual(missed.status, "not_found_skipped")

    def test_reopen_skipped_job_resets_misses_and_keeps_candidate_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            job = queue.add(["The KWL Hub"])["created"][0]
            queue.claim(limit=1, worker="agent")
            queue.record_search_miss(job["id"], reason="complete search chain")

            reopened = queue.reopen(
                job["id"],
                reason="人工发现 APKPure 精确页面",
                candidate_url=(
                    "https://apkpure.com/cn/the-kwl-hub/"
                    "com.magicbox.klettlp"
                ),
            )

            self.assertEqual(reopened.status, "retry")
            self.assertEqual(reopened.search_miss_count, 0)
            self.assertEqual(reopened.claimed_by, "")
            self.assertIn("com.magicbox.klettlp", reopened.candidate_url)
            claimed = queue.claim(limit=1, worker="agent")[0]
            self.assertEqual(claimed.id, job["id"])
            self.assertEqual(claimed.candidate_url, reopened.candidate_url)
            with self.assertRaisesRegex(ValueError, "exact candidate blocks"):
                queue.record_search_miss(
                    job["id"],
                    reason="download did not create a file",
                )

    def test_cloudflare_failure_defers_exact_candidate_instead_of_clearing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            job = queue.add(["Reel Rush"])["created"][0]
            queue.claim(limit=1, worker="agent")
            candidate = "https://apkpure.com/reel-rush/package/download"
            queue.record_candidate(job["id"], url=candidate)

            deferred = queue.clear_candidate(
                job["id"],
                reason="Cloudflare verification timeout after Chrome and Faker",
            )

            self.assertEqual(deferred.status, "retry")
            self.assertEqual(deferred.candidate_url, candidate)
            self.assertEqual(deferred.claimed_by, "")
            self.assertIn("等待重试", deferred.last_error)

    def test_pending_jobs_run_before_candidate_waiting_for_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            blocked = queue.add(["Cloudflare Candidate"])["created"][0]
            queue.claim(limit=1, worker="agent")
            queue.record_candidate(
                blocked["id"],
                url="https://apkpure.com/cloudflare/app/download",
            )
            queue.clear_candidate(
                blocked["id"],
                reason="d.apkpure returned HTML and browser verification timed out",
            )
            pending = queue.add(["Fresh Pending App"])["created"][0]

            claimed = queue.claim(limit=1, worker="next-agent")

            self.assertEqual([job.id for job in claimed], [pending["id"]])
            self.assertEqual(queue.get(blocked["id"]).status, "retry")

    def test_automatic_claim_reserves_one_blocked_slot_then_returns_to_normal_jobs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            blocked = queue.add(["Cloudflare Candidate"])["created"][0]
            queue.claim(limit=1, worker="setup-agent")
            queue.record_candidate(
                blocked["id"],
                url="https://apkpure.com/cloudflare/com.example.blocked/download",
            )
            queue.clear_candidate(
                blocked["id"],
                reason="Cloudflare verification timeout after Chrome",
            )
            normal = queue.add(["Fresh Normal App"])["created"][0]

            blocked_claim = queue.claim(
                limit=10,
                worker="automatic-blocked-agent",
                automatic=True,
            )
            normal_claim = queue.claim(
                limit=10,
                worker="automatic-normal-agent",
                automatic=True,
            )

            self.assertEqual([job.id for job in blocked_claim], [blocked["id"]])
            self.assertEqual([job.id for job in normal_claim], [normal["id"]])

    def test_automatic_claim_throttles_blocked_candidates_globally(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            jobs = queue.add(["Blocked One", "Blocked Two"])["created"]
            queue.claim(limit=2, worker="setup-agent")
            for job in jobs:
                queue.record_candidate(
                    job["id"],
                    url=f"https://apkpure.com/app/com.example.blocked{job['id']}",
                )
                queue.clear_candidate(
                    job["id"],
                    reason="browser_required after Cloudflare timeout",
                )

            first = queue.claim(
                limit=10,
                worker="automatic-one",
                automatic=True,
            )
            second = queue.claim(
                limit=10,
                worker="automatic-two",
                automatic=True,
            )

            self.assertEqual(len(first), 1)
            self.assertEqual(second, [])
            remaining = queue.list_jobs(status="retry")
            self.assertEqual(len(remaining), 1)

            manual = queue.claim(limit=1, worker="manual-agent")
            self.assertEqual([job.id for job in manual], [remaining[0].id])

    def test_lists_only_exact_candidates_blocked_by_browser_challenges(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            jobs = queue.add(
                ["Cloudflare App", "HTML Download App", "TLS Only App"]
            )["created"]
            queue.claim(limit=3, worker="agent")
            for job in jobs:
                queue.record_candidate(
                    job["id"],
                    url=f"https://example.com/app/com.example.app{job['id']}",
                )
            queue.clear_candidate(
                jobs[0]["id"],
                reason="Cloudflare verification timeout after Chrome",
            )
            queue.clear_candidate(
                jobs[1]["id"],
                reason="d.apkpure file entry returned HTML",
            )
            queue.clear_candidate(
                jobs[2]["id"],
                reason="TLS connection closed before page verification",
            )

            blocked = queue.list_cloudflare_blocked()

            self.assertEqual(
                {job.keyword for job in blocked},
                {"Cloudflare App", "HTML Download App"},
            )
            self.assertEqual(queue.count_cloudflare_blocked(), 2)

    def test_reopen_completed_job_keeps_original_queue_position(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            jobs = queue.add(["Earlier App", "Downloaded Elsewhere"])["created"]
            queue.claim(limit=2, worker="agent")
            queue.update(
                jobs[0]["id"],
                status="completed",
                delivery_directory="downloads/earlier-app",
            )
            queue.update(
                jobs[1]["id"],
                status="completed",
                delivery_directory="downloads/downloaded-elsewhere",
            )

            reopened = queue.reopen(
                jobs[0]["id"],
                reason="客户端磁盘已满，未能保存交付包",
            )

            self.assertEqual(reopened.status, "retry")
            self.assertEqual(reopened.delivery_directory, "")
            self.assertEqual(reopened.search_miss_count, 0)
            self.assertEqual(
                queue.claim(limit=1, worker="repair-agent")[0].id,
                jobs[0]["id"],
            )

    def test_manual_confirmation_moves_job_and_saves_edited_reason(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            job = queue.add(["Manually Reviewed App"])["created"][0]
            queue.claim(limit=1, worker="agent")
            skipped = queue.record_search_miss(
                job["id"],
                reason="automatic final reason",
            )

            confirmed = queue.confirm_not_found(
                skipped.id,
                reason="官网与全部可信来源均已人工复核，确认没有 APK",
            )

            self.assertEqual(confirmed.status, "manual_not_found")
            self.assertEqual(
                confirmed.last_error,
                "官网与全部可信来源均已人工复核，确认没有 APK",
            )
            self.assertEqual(queue.snapshot()["counts"]["not_found_skipped"], 0)
            self.assertEqual(queue.snapshot()["counts"]["manual_not_found"], 1)
            self.assertEqual(
                queue.list_jobs(status="manual_not_found")[0].id,
                skipped.id,
            )

            edited = queue.confirm_not_found(
                skipped.id,
                reason="人工复核完成：只有 iOS 版本",
            )
            self.assertEqual(edited.status, "manual_not_found")
            self.assertEqual(edited.last_error, "人工复核完成：只有 iOS 版本")

    def test_paid_skip_can_be_manually_confirmed_like_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            jobs = queue.add(["Paid App", "Pending App"])["created"]
            queue.claim(limit=1, worker="agent")
            paid = queue.update(jobs[0]["id"], status="paid_skipped")

            confirmed = queue.confirm_not_found(
                paid.id,
                reason="人工确认：官方页面当前显示购买价格",
            )
            self.assertEqual(confirmed.status, "manual_not_found")
            self.assertEqual(
                confirmed.last_error,
                "人工确认：官方页面当前显示购买价格",
            )
            self.assertEqual(queue.snapshot()["counts"]["paid_skipped"], 0)
            self.assertEqual(queue.snapshot()["counts"]["manual_not_found"], 1)
            with self.assertRaisesRegex(ValueError, "reason is required"):
                queue.confirm_not_found(jobs[1]["id"], reason=" ")

    def test_manual_confirmation_supports_ios_paid_and_not_found_categories(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            jobs = queue.add(["iOS Only", "Paid App", "Missing App"])[
                "created"
            ]
            for job in jobs:
                queue.claim_specific(job["id"], worker="agent")
                queue.update(job["id"], status="not_found_skipped")

            ios = queue.confirm_not_found(
                jobs[0]["id"],
                reason="人工确认只有 iOS 版本",
                category="ios",
            )
            paid = queue.confirm_not_found(
                jobs[1]["id"],
                reason="人工确认需要购买",
                category="paid",
            )
            missing = queue.confirm_not_found(
                jobs[2]["id"],
                reason="人工确认没有 Android 安装包",
                category="not_found",
            )

            self.assertEqual(ios.status, "manual_ios")
            self.assertEqual(paid.status, "manual_paid")
            self.assertEqual(missing.status, "manual_not_found")
            counts = queue.snapshot()["counts"]
            self.assertEqual(counts["manual_ios"], 1)
            self.assertEqual(counts["manual_paid"], 1)
            self.assertEqual(counts["manual_not_found"], 1)

            reclassified = queue.confirm_not_found(
                ios.id,
                reason="重新确认是付费应用",
                category="paid",
            )
            self.assertEqual(reclassified.status, "manual_paid")
            with self.assertRaisesRegex(ValueError, "unsupported"):
                queue.confirm_not_found(
                    missing.id,
                    reason="无效分类",
                    category="other",
                )

    def test_paid_skipped_reason_can_be_edited_without_changing_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            job = queue.add(["Paid App"])["created"][0]
            queue.claim(limit=1, worker="agent")
            paid = queue.update(job["id"], status="paid_skipped")

            edited = queue.update_skipped_reason(
                paid.id,
                reason="人工复核：Google Play 当前显示购买价格",
            )

            self.assertEqual(edited.status, "paid_skipped")
            self.assertEqual(
                edited.last_error,
                "人工复核：Google Play 当前显示购买价格",
            )
            self.assertEqual(queue.snapshot()["counts"]["paid_skipped"], 1)
            self.assertEqual(queue.snapshot()["counts"]["manual_not_found"], 0)

    def test_initialize_migrates_legacy_queue_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "state" / "queue.sqlite3"
            database.parent.mkdir(parents=True)
            import sqlite3

            connection = sqlite3.connect(database)
            connection.executescript(
                """
                CREATE TABLE keyword_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    keyword TEXT NOT NULL,
                    normalized_keyword TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    claimed_by TEXT,
                    claimed_at REAL,
                    completed_at REAL,
                    delivery_directory TEXT,
                    last_error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    CHECK (
                        status IN (
                            'pending',
                            'processing',
                            'completed',
                            'retry',
                            'paid_skipped'
                        )
                    )
                );
                INSERT INTO keyword_jobs (
                    keyword,
                    normalized_keyword,
                    status,
                    attempt_count,
                    created_at,
                    updated_at
                ) VALUES ('Legacy App', 'legacy app', 'pending', 2, 1, 1);
                """
            )
            connection.close()

            queue = self.make_queue(Path(temporary))
            job = queue.list_jobs()[0]

            self.assertEqual(job.keyword, "Legacy App")
            self.assertEqual(job.attempt_count, 2)
            self.assertEqual(job.search_miss_count, 0)
            queue.claim(limit=1, worker="agent")
            skipped = queue.record_search_miss(
                job.id,
                reason="complete search chain had no result",
            )
            self.assertEqual(skipped.status, "not_found_skipped")
            confirmed = queue.confirm_not_found(
                skipped.id,
                reason="legacy record manually confirmed",
            )
            self.assertEqual(confirmed.status, "manual_not_found")

    def test_release_worker_returns_unfinished_jobs_to_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = self.make_queue(Path(temporary))
            queue.add(["One", "Two"])
            jobs = queue.claim(limit=2, worker="apk-agent")
            queue.update(jobs[0].id, status="paid_skipped")

            released = queue.release_worker(
                "apk-agent",
                reason="worker exited",
            )
            snapshot = queue.snapshot()

            self.assertEqual(released, 1)
            self.assertEqual(snapshot["counts"]["paid_skipped"], 1)
            self.assertEqual(snapshot["counts"]["retry"], 1)
            retry_job = queue.list_jobs(status="retry")[0]
            self.assertEqual(retry_job.last_error, "worker exited")

    def test_clean_keyword_removes_controls_and_collapses_whitespace(self) -> None:
        self.assertEqual(clean_keyword("  My\u0000  App\nName  "), "My App Name")

    def test_delivery_directory_must_match_queued_keyword(self) -> None:
        self.assertTrue(directory_matches_keyword("google-maps", "Google Maps"))
        self.assertTrue(
            directory_matches_keyword(
                "sam's-club-shopping",
                "Sam’s Club Shopping",
            )
        )
        self.assertFalse(directory_matches_keyword("aaa-mobile", "Google Maps"))


if __name__ == "__main__":
    unittest.main()
