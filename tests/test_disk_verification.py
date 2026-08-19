"""P0-D service wiring: apply_disk_verification must override DB byte counts
with real on-disk state, and fetch_queue_page keeps its two-SELECT contract.
"""

from __future__ import annotations

from pathlib import Path

from core.database import LibraryVault
from core.services.download_service import DownloadService


def _seed_one(vault: LibraryVault, rj_id: str, work_dir: Path,
              status: str = "downloading") -> None:
    with vault._lock:
        vault.conn.execute(
            "INSERT INTO works (rj_id, title, circle, cover_url, status, local_path) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (rj_id, "Title", "Circle", "", status, str(work_dir)),
        )
        vault.conn.executemany(
            """INSERT INTO downloads
               (id, rj_id, track_title, local_path, status,
                downloaded_bytes, total_bytes, error, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            [
                (f"{rj_id}:0", rj_id, "a.mp3", str(work_dir / "a.mp3"),
                 "registered", 100, 100, None),
                (f"{rj_id}:1", rj_id, "b.mp3", str(work_dir / "b.mp3"),
                 "downloading", 100, 100, None),
                (f"{rj_id}:2", rj_id, "c.mp3", str(work_dir / "c.mp3"),
                 "failed", 0, 100, "boom"),
            ],
        )


def test_disk_verification_overrides_stale_registered_bytes(tmp_path: Path) -> None:
    """DB says both a.mp3 and b.mp3 are fully downloaded, but only a.mp3
    actually exists on disk.  Progress must reflect disk, not the DB."""
    work_dir = tmp_path / "RJ00000001"
    work_dir.mkdir()
    (work_dir / "a.mp3").write_bytes(b"a" * 100)
    (work_dir / "b.mp3.part").write_bytes(b"b" * 40)  # .part actual size

    vault = LibraryVault(tmp_path / "history.db")
    try:
        _seed_one(vault, "RJ00000001", work_dir)
        page = DownloadService(vault).fetch_queue_page(
            status_filter="all", page_size=20)
        raw = next(item for item in page.items if item.rj_id == "RJ00000001")
        assert raw.verified_bytes is None  # not yet disk-verified

        verified_page = DownloadService(vault).apply_disk_verification(page)
        item = next(i for i in verified_page.items if i.rj_id == "RJ00000001")
        assert item.verified_bytes == 140          # 100 final + 40 .part
        assert item.verified_files == 1
        assert item.overage_file_count == 0
        assert 0.0 < item.progress < 1.0           # 140/300, never over 100%
    finally:
        vault.close()


def test_disk_verification_never_exceeds_100_percent(tmp_path: Path) -> None:
    """DB downloaded_bytes sum can exceed total; verification must clamp."""
    work_dir = tmp_path / "RJ00000002"
    work_dir.mkdir()
    (work_dir / "a.mp3").write_bytes(b"a" * 500)   # oversized final file
    (work_dir / "b.mp3").write_bytes(b"b" * 100)
    (work_dir / "c.mp3.part").write_bytes(b"c" * 100)

    vault = LibraryVault(tmp_path / "history.db")
    try:
        _seed_one(vault, "RJ00000002", work_dir)
        page = DownloadService(vault).fetch_queue_page(
            status_filter="all", page_size=20)
        item = next(i for i in
                    DownloadService(vault).apply_disk_verification(page).items
                    if i.rj_id == "RJ00000002")
        assert item.overage_file_count == 1        # a.mp3 oversized
        assert item.progress <= 1.0
        assert 0.0 <= item.verified_bytes <= 300
    finally:
        vault.close()


def test_fetch_queue_page_still_uses_two_selects(tmp_path: Path) -> None:
    """apply_disk_verification is separate; the snapshot stays two SELECTs."""
    work_dir = tmp_path / "RJ00000003"
    work_dir.mkdir()
    vault = LibraryVault(tmp_path / "history.db")
    try:
        _seed_one(vault, "RJ00000003", work_dir)
        selects: list[str] = []
        vault.conn.set_trace_callback(
            lambda sql: selects.append(sql)
            if sql.lstrip().upper().startswith(("SELECT", "WITH")) else None)
        DownloadService(vault).fetch_queue_page(page_size=24)
        vault.conn.set_trace_callback(None)
        assert len(selects) == 2
    finally:
        vault.close()
