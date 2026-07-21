#!/usr/bin/env python3
"""Run TAKEOVER-T6 against a fully disposable library and SQLite database."""
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.database import LibraryVault
from core.intake_fs import ExternalIntakeSandboxExecutor
from core.intake_journal import request_from_plan_action
from tools.external_intake import annotate_plan_with_database, scan_structure

SANDBOX_MARKER = ".arsm-intake-sandbox.json"


def _prepare_sandbox(base: Path) -> None:
    blocked = {Path(base.anchor).resolve(), Path.home().resolve(), REPO_ROOT.resolve()}
    if base.resolve(strict=False) in blocked:
        raise RuntimeError(f"refusing unsafe sandbox path: {base}")
    marker = base / SANDBOX_MARKER
    if base.exists():
        if not marker.is_file():
            raise RuntimeError(
                f"refusing to delete existing unmarked directory: {base}"
            )
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"invalid sandbox marker: {marker}") from exc
        if payload.get("purpose") != "arsm-intake-acceptance":
            raise RuntimeError(f"unrecognized sandbox marker: {marker}")
        shutil.rmtree(base)
    base.mkdir(parents=True)
    marker.write_text(
        json.dumps(
            {
                "purpose": "arsm-intake-acceptance",
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


class FailingVault:
    def update_external_intake_paths(self, *args, **kwargs):
        return {
            "success": False,
            "error_code": "injected_db_failure",
            "error": "injected database failure",
        }


def _write_work(directory: Path, *, title_layer: str | None = None) -> Path:
    base = directory / title_layer if title_layer else directory
    (base / "audio").mkdir(parents=True, exist_ok=True)
    (base / "audio" / "track01.mp3").write_bytes(b"audio" * 128)
    (base / "cover.jpg").write_bytes(b"cover" * 16)
    (base / "metadata.json").write_text(
        json.dumps({"title": directory.name}, ensure_ascii=False), encoding="utf-8"
    )
    return directory


def _seed(vault: LibraryVault, rj_id: str, source: Path) -> None:
    track = next(source.rglob("track01.mp3"))
    vault.execute_write(
        """INSERT INTO works (rj_id,title,local_path,status,size_bytes)
           VALUES (?, ?, ?, 'verified', ?)""",
        (rj_id, source.name, str(source.resolve()), track.stat().st_size),
    )
    vault.execute_write(
        """INSERT INTO downloads
           (id,rj_id,track_title,local_path,status,downloaded_bytes,total_bytes)
           VALUES (?,?,'track01',?,'completed',?,?)""",
        (f"{rj_id}:track01", rj_id, str(track.resolve()), track.stat().st_size, track.stat().st_size),
    )
    vault.execute_write(
        """INSERT INTO library_items
           (rj_id,folder_path,folder_name,total_files,total_size,audio_count,
            image_count,has_audio,has_cover,warnings_json)
           VALUES (?,?,?,3,?,1,1,1,1,'[]')""",
        (rj_id, str(source.resolve()), source.name, track.stat().st_size),
    )
    vault.execute_write(
        """INSERT INTO library_index
           (rj_id,library_path,work_dir,status,size_bytes,file_count)
           VALUES (?,?,?,'found',?,3)""",
        (rj_id, str(source.parent.resolve()), str(source.resolve()), track.stat().st_size),
    )


def _action(plan: dict[str, Any], rj_id: str) -> dict[str, Any]:
    return next(item for item in plan["actions"] if item.get("rj_id") == rj_id)


def _db_work_path(vault: LibraryVault, rj_id: str) -> str:
    row = vault.conn.execute("SELECT local_path FROM works WHERE rj_id=?", (rj_id,)).fetchone()
    return str(row[0]) if row else ""


def run_acceptance(base_dir: str | Path) -> dict[str, Any]:
    base = Path(base_dir).expanduser().resolve(strict=False)
    _prepare_sandbox(base)
    incoming = base / "incoming"
    quarantine = base / "quarantine"
    journals = base / "journals"
    incoming.mkdir()
    quarantine.mkdir()

    # Executable rename candidate.
    rename_source = _write_work(incoming / "RJ01010001 Rename Sample")
    # Canonical RJ root with files at root: metadata title is required, so review only.
    title_review = incoming / "RJ01010002"
    title_review.mkdir()
    (title_review / "track.mp3").write_bytes(b"title-review")
    # Duplicate RJ candidates.
    _write_work(incoming / "RJ01010003 Copy A")
    _write_work(incoming / "RJ01010003 Copy B")
    # Quarantine candidates.
    (incoming / "RJ01010004").mkdir()
    part_source = incoming / "RJ01010005 Partial"
    part_source.mkdir()
    (part_source / "track.mp3.part").write_bytes(b"partial")
    # Already normalized sample.
    _write_work(incoming / "RJ01010009", title_layer="Normalized Title")

    db_path = base / "history.db"
    vault = LibraryVault(db_path)
    try:
        _seed(vault, "RJ01010001", rename_source)
        duplicate_primary = incoming / "primary-outside-plan" / "RJ01010003"
        duplicate_primary.mkdir(parents=True)
        _write_work(duplicate_primary)
        _seed(vault, "RJ01010003", duplicate_primary)

        first = annotate_plan_with_database(
            scan_structure(incoming, quarantine), vault
        )
        classifications = {
            item.get("rj_id") or item.get("source_name"): item["classification"]
            for item in first["actions"]
        }
        rename_action = _action(first, "RJ01010001")
        rename_request = request_from_plan_action(rename_action, sandbox_root=base)
        success_journal = ExternalIntakeSandboxExecutor(vault, journals).execute(rename_request)
        if not success_journal.success:
            raise RuntimeError(f"rename fixture failed: {success_journal.error_code}")

        target = incoming / "RJ01010001"
        expected_track = target / "Rename Sample" / "audio" / "track01.mp3"
        if not expected_track.exists():
            raise RuntimeError("mapped target file is missing")
        if _db_work_path(vault, "RJ01010001") != str(target.resolve()):
            raise RuntimeError("database path does not match committed target")

        second = annotate_plan_with_database(
            scan_structure(incoming, quarantine), vault
        )
        second_action = _action(second, "RJ01010001")
        idempotent = second_action["classification"] == "already_normalized"

        # DB failure must restore source and leave the target absent.
        db_fail_source = _write_work(incoming / "RJ01010006 Database Failure")
        _seed(vault, "RJ01010006", db_fail_source)
        db_fail_plan = annotate_plan_with_database(
            scan_structure(incoming, quarantine), vault
        )
        db_fail_request = request_from_plan_action(
            _action(db_fail_plan, "RJ01010006"), sandbox_root=base
        )
        db_fail_journal = ExternalIntakeSandboxExecutor(
            FailingVault(), journals
        ).execute(db_fail_request)

        # A post-commit failure must stop with rollback preserved, then recover.
        cleanup_source = _write_work(incoming / "RJ01010007 Cleanup Failure")
        _seed(vault, "RJ01010007", cleanup_source)
        cleanup_plan = annotate_plan_with_database(
            scan_structure(incoming, quarantine), vault
        )
        cleanup_request = request_from_plan_action(
            _action(cleanup_plan, "RJ01010007"), sandbox_root=base
        )

        def fail_after_db(stage, journal):
            if stage == "after_db_update":
                raise OSError("injected cleanup failure")

        cleanup_executor = ExternalIntakeSandboxExecutor(
            vault, journals, fault_injector=fail_after_db
        )
        cleanup_journal = cleanup_executor.execute(cleanup_request)
        recovered = ExternalIntakeSandboxExecutor(vault, journals).recover(
            journals / f"{cleanup_request.transaction_id}.json"
        )

        duplicate_path_after = _db_work_path(vault, "RJ01010003")
        report = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "sandbox": str(base),
            "database": str(db_path),
            "first_plan_counts": first["counts"],
            "fixture_classifications": classifications,
            "success_transaction": success_journal.to_dict(),
            "idempotent_second_scan": idempotent,
            "second_classification": second_action["classification"],
            "database_failure": {
                "state": db_fail_journal.state,
                "error_code": db_fail_journal.error_code,
                "source_restored": db_fail_source.exists(),
                "target_absent": not (incoming / "RJ01010006").exists(),
            },
            "cleanup_failure": {
                "initial_state": cleanup_journal.state,
                "stop_required": cleanup_journal.stop_required,
                "recovered_state": recovered.state,
                "recovered_success": recovered.success,
            },
            "duplicate_primary_unchanged": duplicate_path_after == str(duplicate_primary.resolve()),
            "checks": {
                "rename_completed": success_journal.success,
                "mapped_file_exists": expected_track.exists(),
                "db_matches_target": _db_work_path(vault, "RJ01010001") == str(target.resolve()),
                "second_scan_idempotent": idempotent,
                "title_layer_requires_review": _action(first, "RJ01010002")["classification"] == "needs_title_layer",
                "duplicate_requires_review": all(
                    item["classification"] == "duplicate_review"
                    for item in first["actions"]
                    if item.get("rj_id") == "RJ01010003"
                ),
                "empty_is_quarantine": _action(first, "RJ01010004")["classification"] == "quarantine_candidate",
                "part_is_quarantine": _action(first, "RJ01010005")["classification"] == "quarantine_candidate",
                "database_failure_rolled_back": db_fail_journal.state == "rolled_back" and db_fail_source.exists(),
                "cleanup_failure_recovered": recovered.success and recovered.state == "completed",
                "duplicate_primary_unchanged": duplicate_path_after == str(duplicate_primary.resolve()),
            },
        }
        report["passed"] = all(report["checks"].values())
        report_path = base / "intake_sandbox_acceptance.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["report_path"] = str(report_path)
        return report
    finally:
        vault.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sandbox", help="Disposable output directory")
    parser.add_argument("--keep", action="store_true", help="Keep an auto-created sandbox")
    args = parser.parse_args()

    if args.sandbox:
        report = run_acceptance(args.sandbox)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 1

    with tempfile.TemporaryDirectory(prefix="arsm-intake-acceptance-") as temp:
        report = run_acceptance(temp)
        if args.keep:
            destination = Path.cwd() / f"intake-acceptance-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            shutil.copytree(temp, destination)
            report["kept_at"] = str(destination)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
