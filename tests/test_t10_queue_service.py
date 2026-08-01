from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from core.database import LibraryVault
from core.services.download_service import DownloadService, normalize_rj_id

pytestmark = pytest.mark.portable


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seed(vault: LibraryVault, count: int) -> None:
    works = []
    downloads = []
    for index in range(count):
        rj_id = f"RJ{index + 1:08d}"
        group = index % 5
        work_status = ("downloading", "queued", "paused", "failed", "completed")[group]
        works.append((rj_id, f"Title {index}", "Circle", "", work_status, f"C:/{rj_id}"))
        for file_index in range(3):
            if group == 0:
                status = "downloading" if file_index == 0 else "queued"
                downloaded = 25 if file_index == 0 else 0
            elif group == 1:
                status, downloaded = "queued", 0
            elif group == 2:
                status, downloaded = "paused", 50
            elif group == 3:
                status, downloaded = "failed", 0
            else:
                status, downloaded = "registered", 100
            downloads.append((
                f"{rj_id}:{file_index}", rj_id, f"track-{file_index}.mp3",
                f"C:/{rj_id}/track-{file_index}.mp3", status, downloaded, 100,
                "boom" if status == "failed" else None,
            ))
    with vault._lock:
        vault.conn.executemany(
            """INSERT INTO works
               (rj_id, title, circle, cover_url, status, local_path)
               VALUES (?, ?, ?, ?, ?, ?)""",
            works,
        )
        vault.conn.executemany(
            """INSERT INTO downloads
               (id, rj_id, track_title, local_path, status,
                downloaded_bytes, total_bytes, error, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            downloads,
        )


@pytest.mark.parametrize("count", [10, 50, 100, 200])
def test_queue_snapshot_uses_two_selects_independent_of_task_count(
    tmp_path: Path,
    count: int,
) -> None:
    vault = LibraryVault(tmp_path / "history.db")
    try:
        _seed(vault, count)
        selects: list[str] = []
        vault.conn.set_trace_callback(
            lambda sql: selects.append(sql) if sql.lstrip().upper().startswith(("SELECT", "WITH")) else None
        )
        page = DownloadService(vault).fetch_queue_page(page_size=24)
        vault.conn.set_trace_callback(None)

        assert len(selects) == 2
        assert page.summary.total_tasks == count
        assert len(page.items) <= 24
        assert all(not item.is_terminal for item in page.items)
    finally:
        vault.close()


def test_queue_item_contains_aggregate_progress_current_file_and_error(tmp_path: Path) -> None:
    vault = LibraryVault(tmp_path / "history.db")
    try:
        _seed(vault, 5)
        all_items = DownloadService(vault).fetch_queue_page(
            status_filter="all", page_size=20
        ).items
        active = next(item for item in all_items if item.queue_state == "active")
        failed = next(item for item in all_items if item.queue_state == "failed")
        completed = next(item for item in all_items if item.queue_state == "completed")
        assert active.current_file == "track-0.mp3"
        assert active.progress > 0
        assert active.can_pause is True
        assert failed.error_summary == "boom"
        assert failed.can_retry is True
        assert completed.is_terminal is True
    finally:
        vault.close()


def test_batch_preview_is_read_only_and_classifies_all_sources(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"
    output = tmp_path / "Downloads"
    output.mkdir()
    (output / "RJ00000006 Existing title").mkdir()
    vault = LibraryVault(db_path)
    try:
        vault.execute_write(
            "INSERT INTO works (rj_id, title, status) VALUES (?, ?, ?)",
            ("RJ00000003", "Done", "completed"),
        )
        vault.execute_write(
            """INSERT INTO downloads
               (id, rj_id, status, downloaded_bytes, total_bytes)
               VALUES (?, ?, 'paused', 5, 10)""",
            ("q", "RJ00000004"),
        )
        vault.execute_write(
            """INSERT INTO library_items
               (rj_id, folder_path, folder_name)
               VALUES (?, ?, ?)""",
            ("RJ00000005", str(output / "five"), "five"),
        )
        before = _digest(db_path)
        preview = DownloadService(vault, output_dir=output).preview_enqueue(
            "RJ00000001 https://asmr.one/work/RJ00000002 "
            "RJ00000001 bad RJ00000003 RJ00000004 RJ00000005 RJ00000006",
            active_rj_ids={"RJ00000002"},
        )
        after = _digest(db_path)

        assert preview.ready == ("RJ00000001",)
        assert preview.duplicate_input == ("RJ00000001",)
        assert preview.invalid_tokens == ("bad",)
        assert preview.already_active == ("RJ00000002",)
        assert preview.already_completed == ("RJ00000003",)
        assert preview.already_in_queue == ("RJ00000004",)
        assert preview.already_in_library == ("RJ00000005", "RJ00000006")
        assert before == after
    finally:
        vault.close()


def test_normalize_rj_supports_number_code_and_asmr_one_url() -> None:
    assert normalize_rj_id("RJ01583845") == "RJ01583845"
    assert normalize_rj_id("1583845") == "RJ1583845"
    assert normalize_rj_id("https://asmr.one/work/RJ01583845") == "RJ01583845"
    assert normalize_rj_id("RJ123") is None
    assert normalize_rj_id("prefixRJ01583845") is None
