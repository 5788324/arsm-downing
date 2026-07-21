#!/usr/bin/env python3
"""Run TAKEOVER-T8B resource library rebuild acceptance in a temp sandbox."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.database import LibraryVault


def _write(root: Path, folder: str, files: dict[str, bytes]) -> Path:
    work = root / folder
    for relative, data in files.items():
        target = work / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return work


def run_acceptance(base_dir: str | Path) -> dict:
    base = Path(base_dir).expanduser().resolve()
    base.mkdir(parents=True, exist_ok=False)
    root_a = base / "library-a"
    root_b = base / "library-b"
    primary = _write(root_a, "RJ01030001 Primary", {
        "audio/track.mp3": b"a" * 64,
        "cover.jpg": b"c" * 8,
    })
    duplicate = _write(root_b, "RJ01030001 Duplicate", {"other.mp3": b"b" * 16})
    nested = _write(root_a / "group", "RJ01030002 Nested", {"chapter/inner.flac": b"d" * 32})

    vault = LibraryVault(base / "history.db")
    try:
        vault.execute_write(
            "INSERT INTO works(rj_id,title,local_path,status) VALUES (?,?,?,'external')",
            ("RJ01030001", "Primary", str(primary)),
        )
        vault.execute_write(
            """INSERT INTO library_index
               (rj_id,library_path,work_dir,status,size_bytes,file_count,scanned_at)
               VALUES ('RJ01999999','old','old/work','found',1,1,'old')"""
        )
        first = vault.rebuild_library([str(root_a), str(root_b)])
        item = vault.conn.execute(
            "SELECT folder_path,warnings_json FROM library_items WHERE rj_id='RJ01030001'"
        ).fetchone()
        nested_item = vault.conn.execute(
            "SELECT folder_path FROM library_items WHERE rj_id='RJ01030002'"
        ).fetchone()
        index_count = vault.conn.execute(
            "SELECT COUNT(*) FROM library_index WHERE rj_id='RJ01030001'"
        ).fetchone()[0]

        # Remove one discovered work and rebuild; stale index/item must disappear.
        for path in sorted(nested.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        nested.rmdir()
        second = vault.rebuild_library([str(root_a), str(root_b)])
        nested_after = vault.conn.execute(
            "SELECT COUNT(*) FROM library_items WHERE rj_id='RJ01030002'"
        ).fetchone()[0]
        nested_work_status = vault.conn.execute(
            "SELECT status FROM works WHERE rj_id='RJ01030002'"
        ).fetchone()[0]

        tracks = [{
            "type": "folder",
            "children": [{"type": "audio", "title": "track.mp3"}],
        }]
        verified = vault.verify_library_item("RJ01030001", str(primary), tracks)

        checks = {
            "first_rebuild_success": first["success"] is True,
            "duplicate_paths_retained": index_count == 2,
            "existing_primary_preserved": Path(item["folder_path"]) == primary,
            "duplicate_warning_recorded": "duplicate_rj" in json.loads(item["warnings_json"]),
            "nested_directory_discovered": Path(nested_item["folder_path"]) == nested,
            "stale_item_removed": nested_after == 0,
            "missing_work_marked": nested_work_status == "missing",
            "recursive_track_verified": verified == "verified",
            "old_index_removed": first["removed_index"] == 1,
            "second_rebuild_success": second["success"] is True,
        }
        report = {
            "passed": all(checks.values()),
            "checks": checks,
            "first": first,
            "second": second,
        }
        report_path = base / "library_rebuild_acceptance.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["report_path"] = str(report_path)
        return report
    finally:
        vault.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sandbox")
    args = parser.parse_args()
    if args.sandbox:
        report = run_acceptance(args.sandbox)
    else:
        with tempfile.TemporaryDirectory(prefix="arsm-library-rebuild-") as temp:
            report = run_acceptance(Path(temp) / "sandbox")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["passed"] else 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
