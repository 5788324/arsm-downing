"""Portable RC10 compatibility checks for backlog and library queries."""
from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.database import LibraryVault
from tools.backlog_list import run_backlog_list
from tools.backlog_reenable import dry_run as reenable_dry, load_rj_ids_from_file

passed = failed = 0


def check(name: str, condition: bool) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def add_download(vault: LibraryVault, rj_id: str, suffix: str, status: str, path: Path) -> None:
    vault.execute_write(
        """INSERT INTO downloads
           (id,rj_id,track_title,local_path,status,downloaded_bytes,total_bytes,updated_at)
           VALUES (?,?,?,?,?,0,100,'2026-07-20T00:00:00')""",
        (f"{rj_id}:{suffix}", rj_id, suffix, str(path), status),
    )


print("=== Portable RC10 Compatibility ===\n")
with TemporaryDirectory(prefix="arsm_rc10_") as raw:
    root = Path(raw)
    db_path = root / "history.db"
    vault = LibraryVault(db_path)
    try:
        for index, rj_id in enumerate(("RJ01000001", "RJ01000002", "RJ01510133"), start=1):
            folder = root / rj_id
            folder.mkdir()
            vault.execute_write(
                "INSERT INTO works (rj_id,title,local_path,status,size_bytes) VALUES (?,?,?,?,?)",
                (rj_id, f"Title {index}", str(folder), "completed", index * 100),
            )
            vault.execute_write(
                """INSERT INTO library_items
                   (rj_id,folder_path,folder_name,total_files,total_size,audio_count,image_count,
                    video_count,other_count,has_audio,has_cover,warnings_json,scan_run_id,scanned_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    rj_id,
                    str(folder),
                    folder.name,
                    index + 1,
                    index * 100,
                    1,
                    1 if index == 1 else 0,
                    0,
                    0,
                    1,
                    1 if index == 1 else 0,
                    "[]" if index != 3 else '["warning"]',
                    "test",
                    "2026-07-20T00:00:00",
                ),
            )
        add_download(vault, "RJ01000001", "ignored", "ignored", root / "i.mp3")
        add_download(vault, "RJ01000002", "stale", "stale", root / "s.mp3")
        add_download(vault, "RJ01000002", "completed", "completed", root / "c.mp3")
        add_download(vault, "RJ01510133", "ignored", "ignored", root / "x.mp3")
    finally:
        vault.close()

    groups, summary, candidates = run_backlog_list(
        source="all",
        limit=20,
        sort_by="downloads_desc",
        db_path=db_path,
        report_root=root / "reports",
    )
    check("backlog candidates returned", len(candidates) == 3)
    check("specific RJ remains visible", any(item["rj_id"] == "RJ01510133" for item in candidates))
    check("all-row aggregation works", next(item for item in candidates if item["rj_id"] == "RJ01000002")["completed_count"] == 1)
    check("report row count", summary["total_download_rows"] == 4)
    check("groups generated", bool(groups))

    selected_file = root / "selected.txt"
    selected_file.write_text("# portable\nRJ01000001\nRJ01000002\n", encoding="utf-8")
    selected = load_rj_ids_from_file(selected_file)
    preview = reenable_dry(selected, db_path=db_path)
    check("RJ file parsed", selected == ["RJ01000001", "RJ01000002"])
    check("dry-run targets two rows", preview["totals"]["total_rows"] == 2)
    check("completed not targeted", all(
        row["old_status"] in {"stale", "ignored"}
        for work in preview["would_update"]
        for row in work["details"]
    ))

    vault = LibraryVault.open_read_only(db_path)
    try:
        items = vault.get_library_items(limit=5)
        search = vault.get_library_items(search="RJ010", limit=10)
        audio = vault.get_library_items(filter_audio=True, limit=5)
        missing_cover = vault.get_library_items(filter_cover=True, limit=5)
        warnings = vault.get_library_items(filter_warnings=True, limit=5)
        library_summary = vault.get_library_summary()
        pending = vault.get_pending_downloads()
        pending_rjs = vault.get_pending_rj_ids()
    finally:
        vault.close()

    check("library items returned", len(items) == 3)
    check("library search works", len(search) == 2)
    check("audio filter works", len(audio) == 3)
    check("missing-cover filter works", len(missing_cover) == 2)
    check("warning filter works", [item["rj_id"] for item in warnings] == ["RJ01510133"])
    check("library summary works", library_summary["total_works"] == 3 and library_summary["total_files"] == 9)
    check("stale/ignored hidden from pending", not any(item["status"] in {"stale", "ignored"} for item in pending))
    check("stale/ignored RJs hidden from pending set", not {"RJ01000001", "RJ01000002", "RJ01510133"} & set(pending_rjs))

print(f"\n{'=' * 40}")
print(f"Results: {passed} passed, {failed} failed")
print(f"Overall: {'PASS' if failed == 0 else 'FAIL'}")
raise SystemExit(0 if failed == 0 else 1)
