from __future__ import annotations

import sqlite3
import threading
import unittest

from core.download_queue import (
    DownloadQueueQueryService,
    normalize_rj_id,
    preview_rj_input,
)


class _Vault:
    def __init__(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self.conn.executescript(
            """
            CREATE TABLE works (
                rj_id TEXT PRIMARY KEY,
                title TEXT,
                circle TEXT,
                cover_url TEXT,
                status TEXT,
                local_path TEXT,
                downloaded_at TEXT
            );
            CREATE TABLE downloads (
                id TEXT PRIMARY KEY,
                rj_id TEXT,
                status TEXT,
                downloaded_bytes INTEGER,
                total_bytes INTEGER,
                updated_at TEXT
            );
            CREATE TABLE library_index (
                rj_id TEXT,
                status TEXT
            );
            """
        )

    def add_work(self, rj_id: str, status: str, updated_at: str) -> None:
        self.conn.execute(
            """INSERT INTO works
               (rj_id, title, circle, cover_url, status, local_path, downloaded_at)
               VALUES (?, ?, 'Circle', ?, ?, ?, ?)""",
            (
                rj_id,
                f"Title {rj_id}",
                f"https://example.invalid/{rj_id}.jpg",
                status,
                f"C:/{rj_id}",
                updated_at,
            ),
        )

    def add_file(
        self,
        file_id: str,
        rj_id: str,
        status: str,
        downloaded: int,
        total: int,
        updated_at: str,
    ) -> None:
        self.conn.execute(
            """INSERT INTO downloads
               (id, rj_id, status, downloaded_bytes, total_bytes, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (file_id, rj_id, status, downloaded, total, updated_at),
        )


class BatchPreviewTests(unittest.TestCase):
    def test_normalize_rj_id_is_strict(self) -> None:
        self.assertEqual(normalize_rj_id("rj01603020"), "RJ01603020")
        self.assertEqual(normalize_rj_id("1575399"), "RJ1575399")
        self.assertIsNone(normalize_rj_id("RJ123"))
        self.assertIsNone(normalize_rj_id("abcRJ01603020"))

    def test_preview_classifies_without_side_effects(self) -> None:
        preview = preview_rj_input(
            "RJ01603020，1575399;RJ01603020 bad RJ123456",
            active_rj_ids={"RJ1575399"},
            known_rj_ids={"RJ123456"},
        )
        self.assertEqual(preview.ready, ("RJ01603020",))
        self.assertEqual(preview.duplicate_input, ("RJ01603020",))
        self.assertEqual(preview.invalid_tokens, ("bad",))
        self.assertEqual(preview.already_active, ("RJ1575399",))
        self.assertEqual(preview.already_known, ("RJ123456",))
        self.assertEqual(preview.submitted_count, 5)
        self.assertTrue(preview.requires_confirmation)

    def test_multiple_clean_ids_require_batch_confirmation(self) -> None:
        preview = preview_rj_input("RJ00000001 RJ00000002")
        self.assertEqual(preview.ready, ("RJ00000001", "RJ00000002"))
        self.assertTrue(preview.requires_confirmation)


class QueueReadModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.vault = _Vault()
        self.vault.add_work("RJ00000001", "downloading", "2026-07-22T01:00:00")
        self.vault.add_file(
            "1-a", "RJ00000001", "completed", 100, 100,
            "2026-07-22T01:00:01",
        )
        self.vault.add_file(
            "1-b", "RJ00000001", "downloading", 25, 100,
            "2026-07-22T01:00:02",
        )
        self.vault.add_work("RJ00000002", "paused", "2026-07-22T02:00:00")
        self.vault.add_file(
            "2-a", "RJ00000002", "paused", 40, 100,
            "2026-07-22T02:00:01",
        )
        self.vault.add_work("RJ00000003", "completed", "2026-07-22T03:00:00")
        self.vault.add_file(
            "3-a", "RJ00000003", "registered", 100, 100,
            "2026-07-22T03:00:01",
        )
        self.vault.conn.commit()

    def test_working_filter_hides_completed_and_uses_aggregate_rows(self) -> None:
        page = DownloadQueueQueryService(self.vault).fetch_page(
            status_filter="working",
            page_size=24,
        )
        self.assertEqual(
            [item.rj_id for item in page.items],
            ["RJ00000001", "RJ00000002"],
        )
        self.assertEqual(page.total_items, 2)
        self.assertEqual(page.summary.total_tasks, 3)
        self.assertEqual(page.summary.active_tasks, 1)
        self.assertEqual(page.summary.paused_tasks, 1)
        self.assertEqual(page.summary.completed_tasks, 1)
        active = next(
            item for item in page.items if item.rj_id == "RJ00000001"
        )
        self.assertEqual(active.file_count, 2)
        self.assertEqual(active.completed_files, 1)
        self.assertEqual(active.downloading_files, 1)
        self.assertEqual(active.downloaded_bytes, 125)
        self.assertEqual(active.total_bytes, 200)
        self.assertEqual(active.percent, 62.5)
        self.assertEqual(active.queue_state, "active")
        self.assertTrue(active.cover_url.endswith("RJ00000001.jpg"))

    def test_pagination_is_bounded_and_clamped(self) -> None:
        service = DownloadQueueQueryService(self.vault)
        page_1 = service.fetch_page(status_filter="all", page=1, page_size=2)
        page_2 = service.fetch_page(status_filter="all", page=99, page_size=2)
        self.assertEqual(page_1.total_items, 3)
        self.assertEqual(page_1.page_count, 2)
        self.assertEqual(len(page_1.items), 2)
        self.assertEqual(page_2.page, 2)
        self.assertEqual(len(page_2.items), 1)

    def test_status_filters(self) -> None:
        service = DownloadQueueQueryService(self.vault)
        self.assertEqual(
            [i.rj_id for i in service.fetch_page(status_filter="active").items],
            ["RJ00000001"],
        )
        self.assertEqual(
            [i.rj_id for i in service.fetch_page(status_filter="paused").items],
            ["RJ00000002"],
        )
        self.assertEqual(
            [i.rj_id for i in service.fetch_page(status_filter="completed").items],
            ["RJ00000003"],
        )

    def test_terminal_work_ignores_historical_failed_rows(self) -> None:
        self.vault.add_file(
            "3-old", "RJ00000003", "failed", 0, 100,
            "2026-07-20T00:00:00",
        )
        self.vault.conn.commit()
        service = DownloadQueueQueryService(self.vault)
        self.assertNotIn(
            "RJ00000003",
            [item.rj_id for item in service.fetch_page(status_filter="working").items],
        )
        completed = service.fetch_page(status_filter="completed").items
        item = next(row for row in completed if row.rj_id == "RJ00000003")
        self.assertEqual(item.queue_state, "completed")

    def test_orphan_download_is_not_lost(self) -> None:
        self.vault.add_file(
            "4-a", "RJ00000004", "paused", 5, 10,
            "2026-07-22T04:00:00",
        )
        self.vault.conn.commit()
        items = DownloadQueueQueryService(self.vault).fetch_page(
            status_filter="paused"
        ).items
        orphan = next(item for item in items if item.rj_id == "RJ00000004")
        self.assertEqual(orphan.title, "RJ00000004")
        self.assertEqual(orphan.queue_state, "paused")

    def test_preview_input_uses_work_and_library_indexes(self) -> None:
        self.vault.add_work("RJ00000010", "completed", "2026-07-22T00:00:00")
        self.vault.conn.execute(
            "INSERT INTO library_index (rj_id, status) VALUES (?, 'found')",
            ("RJ00000011",),
        )
        self.vault.conn.commit()
        preview = DownloadQueueQueryService(self.vault).preview_input(
            "RJ00000010 RJ00000011 RJ00000012",
            active_rj_ids={"RJ00000012"},
        )
        self.assertEqual(preview.ready, ())
        self.assertEqual(
            preview.already_known,
            ("RJ00000010", "RJ00000011"),
        )
        self.assertEqual(preview.already_active, ("RJ00000012",))


if __name__ == "__main__":
    unittest.main()
