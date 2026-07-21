#!/usr/bin/env python3
"""Run TAKEOVER-T8A migration acceptance in a disposable sandbox."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.database import LibraryVault
from core.migration import MigrationEngine
from core.models import WorkMetadata

SANDBOX_MARKER = ".arsm-migration-sandbox.json"


def _prepare_sandbox(base: Path) -> None:
    resolved = base.resolve(strict=False)
    blocked = {Path(base.anchor).resolve(), Path.home().resolve(), REPO_ROOT.resolve()}
    if resolved in blocked:
        raise RuntimeError(f"refusing unsafe sandbox path: {base}")
    marker = base / SANDBOX_MARKER
    if base.exists():
        if not marker.is_file():
            raise RuntimeError(f"refusing to delete existing unmarked directory: {base}")
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"invalid sandbox marker: {marker}") from exc
        if payload.get("purpose") != "arsm-migration-acceptance":
            raise RuntimeError(f"unrecognized sandbox marker: {marker}")
        shutil.rmtree(base)
    base.mkdir(parents=True)
    marker.write_text(
        json.dumps(
            {
                "purpose": "arsm-migration-acceptance",
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _metadata(rj_id: str) -> WorkMetadata:
    return WorkMetadata(
        rj_id=rj_id,
        title=f"Migration {rj_id}",
        circle="",
        cv=[],
        tags=[],
        price=0,
        source_url="",
        dl_count=0,
        rating=0.0,
        release_date="",
        cover_url="",
    )


def _write_source(root: Path, rj_id: str, *, part: bool = False) -> Path:
    source = root / rj_id
    (source / "audio" / "chapter").mkdir(parents=True)
    (source / "audio" / "track01.mp3").write_bytes(b"audio-one" * 64)
    (source / "audio" / "chapter" / "track02.mp3").write_bytes(b"audio-two" * 32)
    (source / "metadata.json").write_text(
        json.dumps({"rj_id": rj_id}, ensure_ascii=False), encoding="utf-8"
    )
    if part:
        (source / "audio" / "chapter" / "track03.mp3.part").write_bytes(b"partial")
    return source


def _seed(vault: LibraryVault, rj_id: str, source: Path) -> None:
    files = [path for path in source.rglob("*") if path.is_file()]
    size = sum(path.stat().st_size for path in files)
    vault.register(_metadata(rj_id), size, source, status="completed")
    for index, track in enumerate(sorted(source.rglob("*.mp3")), start=1):
        vault.upsert_download(
            f"{rj_id}:{index}",
            rj_id,
            track.stem,
            str(track.resolve()),
            "registered",
            track.stat().st_size,
            track.stat().st_size,
        )
    vault.execute_write(
        """INSERT OR REPLACE INTO library_items
           (rj_id,folder_path,folder_name,total_files,total_size,audio_count,
            image_count,video_count,other_count,has_audio,has_cover,warnings_json)
           VALUES (?,?,?,?,?,2,0,0,1,1,0,'[]')""",
        (rj_id, str(source.resolve()), source.name, len(files), size),
    )
    vault.execute_write(
        """INSERT INTO library_index
           (rj_id,library_path,work_dir,status,size_bytes,file_count)
           VALUES (?,?,?,'found',?,?)""",
        (rj_id, str(source.parent.resolve()), str(source.resolve()), size, len(files)),
    )


class FailingPathVault:
    """Delegate reads but inject one database path-update failure."""

    def __init__(self, vault: LibraryVault):
        self._vault = vault
        self.conn = vault.conn

    def get_safe_migratable_works(self):
        return self._vault.get_safe_migratable_works()

    def get_external_intake_snapshot(self, rj_id: str):
        return self._vault.get_external_intake_snapshot(rj_id)

    def update_external_intake_paths(self, *args, **kwargs):
        return {
            "success": False,
            "error_code": "injected_db_failure",
            "error": "injected database failure",
        }


class DeleteFailEngine(MigrationEngine):
    def _delete_source_tree(self, path: str) -> None:
        raise PermissionError("injected source lock")


def _work_path(vault: LibraryVault, rj_id: str) -> str:
    row = vault.conn.execute(
        "SELECT local_path FROM works WHERE rj_id=?", (rj_id,)
    ).fetchone()
    return str(row[0]) if row else ""


def run_acceptance(base_dir: str | Path) -> dict[str, Any]:
    base = Path(base_dir).expanduser().resolve(strict=False)
    _prepare_sandbox(base)
    source_root = base / "source"
    target_root = base / "target"
    source_root.mkdir()
    target_root.mkdir()
    db_path = base / "history.db"

    vault = LibraryVault(db_path)
    try:
        success_source = _write_source(source_root, "RJ01020001")
        _seed(vault, "RJ01020001", success_source)
        # Deliberately stale DB size: the migration plan must use disk reality.
        vault.execute_write(
            "UPDATE works SET size_bytes=1 WHERE rj_id='RJ01020001'"
        )
        part_source = _write_source(source_root, "RJ01020002", part=True)
        _seed(vault, "RJ01020002", part_source)
        db_fail_source = _write_source(source_root, "RJ01020003")
        _seed(vault, "RJ01020003", db_fail_source)
        delete_fail_source = _write_source(source_root, "RJ01020004")
        _seed(vault, "RJ01020004", delete_fail_source)
        occupied_source = _write_source(source_root, "RJ01020005")
        _seed(vault, "RJ01020005", occupied_source)
        occupied_target = target_root / "RJ01020005"
        occupied_target.mkdir()
        (occupied_target / ".owner").write_text("preserve", encoding="utf-8")

        engine = MigrationEngine(vault)
        first_plan = engine.dry_run(str(target_root))
        success_item = next(
            item for item in first_plan["candidates"] if item["rj_id"] == "RJ01020001"
        )
        success_target = target_root / "RJ01020001"
        success = engine.migrate_one(
            "RJ01020001",
            str(success_source),
            str(success_target),
            target_base=str(target_root),
            expected_manifest_token=success_item["manifest_token"],
        )
        verified = engine.verify_migrated_work(
            "RJ01020001", str(target_root), source_roots=[str(source_root)]
        )
        second_plan = engine.dry_run(str(target_root))

        db_fail_target = target_root / "RJ01020003"
        db_fail = MigrationEngine(FailingPathVault(vault)).migrate_one(
            "RJ01020003",
            str(db_fail_source),
            str(db_fail_target),
            target_base=str(target_root),
        )

        delete_fail_target = target_root / "RJ01020004"
        delete_fail = DeleteFailEngine(vault).migrate_one(
            "RJ01020004",
            str(delete_fail_source),
            str(delete_fail_target),
            target_base=str(target_root),
        )

        occupied = engine.migrate_one(
            "RJ01020005",
            str(occupied_source),
            str(occupied_target),
            target_base=str(target_root),
        )

        checks = {
            "success_completed": success["success"] is True,
            "source_deleted": not success_source.exists(),
            "target_verified": verified["success"] is True,
            "all_db_paths_target": _work_path(vault, "RJ01020001") == str(success_target),
            "second_plan_idempotent": not any(
                item["rj_id"] == "RJ01020001" for item in second_plan["candidates"]
            ),
            "nested_part_rejected": first_plan["skipped_part_file"] >= 1,
            "db_failure_rolled_back": (
                db_fail["success"] is False
                and db_fail["rollback_performed"] is True
                and db_fail_source.exists()
                and not db_fail_target.exists()
            ),
            "delete_failure_rolled_back": (
                delete_fail["error_code"] == "source_delete_failed_rolled_back"
                and delete_fail["rollback_performed"] is True
                and delete_fail_source.exists()
                and not delete_fail_target.exists()
                and _work_path(vault, "RJ01020004") == str(delete_fail_source)
            ),
            "existing_target_preserved": (
                occupied["error_code"] == "target_exists"
                and (occupied_target / ".owner").read_text(encoding="utf-8") == "preserve"
            ),
            "disk_size_used": (
                success_item["db_size_bytes"] == 1
                and success_item["size_bytes"] > success_item["db_size_bytes"]
            ),
        }
        report = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "sandbox": str(base),
            "database": str(db_path),
            "first_plan": {
                "candidate_count": first_plan["candidate_count"],
                "skipped_part_file": first_plan["skipped_part_file"],
                "skipped_target_exists": first_plan["skipped_target_exists"],
                "total_size_bytes": first_plan["total_size_bytes"],
            },
            "success_result": success,
            "verify_result": verified,
            "database_failure": db_fail,
            "source_delete_failure": delete_fail,
            "occupied_target_result": occupied,
            "checks": checks,
            "passed": all(checks.values()),
        }
        report_path = base / "migration_sandbox_acceptance.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        report["report_path"] = str(report_path)
        return report
    finally:
        vault.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sandbox", help="Disposable output directory")
    parser.add_argument("--keep", action="store_true", help="Keep auto-created sandbox")
    args = parser.parse_args()

    if args.sandbox:
        report = run_acceptance(args.sandbox)
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 0 if report["passed"] else 1

    with tempfile.TemporaryDirectory(prefix="arsm-migration-acceptance-") as temp:
        report = run_acceptance(temp)
        if args.keep:
            destination = Path.cwd() / (
                "migration-acceptance-" + datetime.now().strftime("%Y%m%d-%H%M%S")
            )
            shutil.copytree(temp, destination)
            report["kept_at"] = str(destination)
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
