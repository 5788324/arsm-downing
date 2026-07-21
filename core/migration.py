"""Safe cross-disk migration for completed and verified works.

Migration is deliberately independent from the active downloader.  It plans
from the database, builds a filesystem manifest, copies to a unique staging
directory, verifies the exact relative layout, commits the final target, and
then updates all database path references through the unified path transaction.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

from core.migration_manifest import (
    MigrationManifest,
    MigrationManifestError,
    build_migration_manifest,
    compare_manifest_to_tree,
    contains_recursive_part_file,
)

logger = logging.getLogger("echovault.migration")


def _ensure_migration_log_handler() -> None:
    """Attach a dedicated migration.log file handler lazily and only once."""
    try:
        log_dir = Path("logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "migration.log"
        for handler in logger.handlers:
            if isinstance(handler, logging.FileHandler):
                try:
                    if Path(handler.baseFilename).resolve() == log_path.resolve():
                        return
                except OSError:
                    continue
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        logger.addHandler(file_handler)
        if logger.level == logging.NOTSET or logger.level > logging.INFO:
            logger.setLevel(logging.INFO)
    except OSError:
        pass


class MigrationEngine:
    """Handles safe migration of completed/verified works between disks."""

    CLEANUP_PLAN_FILE = Path("logs/migration_cleanup_plan.jsonl")
    def __init__(self, db):
        self.db = db

    @staticmethod
    def _resolve_path(path: str | Path) -> Path:
        return Path(path).expanduser().resolve(strict=False)

    @classmethod
    def _is_same_or_under(cls, path: str | Path, base: str | Path) -> bool:
        try:
            path_norm = os.path.normcase(str(cls._resolve_path(path)))
            base_norm = os.path.normcase(str(cls._resolve_path(base)))
            return os.path.commonpath([path_norm, base_norm]) == base_norm
        except (ValueError, OSError):
            return False

    @classmethod
    def _paths_overlap(cls, first: str | Path, second: str | Path) -> bool:
        return cls._is_same_or_under(first, second) or cls._is_same_or_under(second, first)

    @staticmethod
    def _has_part_files(path: str) -> bool:
        """Compatibility wrapper; partial files are checked recursively."""
        return contains_recursive_part_file(path)

    @classmethod
    def _dir_stats(cls, path: str) -> tuple[int, int]:
        """Return exact readable file count and total bytes for a directory tree."""
        try:
            manifest = build_migration_manifest(path)
        except MigrationManifestError:
            return 0, 0
        return manifest.file_count, manifest.total_bytes

    @classmethod
    def get_disk_space_check(
        cls,
        target_base: str,
        planned_size_bytes: int,
        headroom_ratio: float = 0.1,
    ) -> dict:
        """Return target-drive free space readiness for a migration plan."""
        target_path = cls._resolve_path(target_base)
        free_bytes = 0
        probe = target_path
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        try:
            free_bytes = shutil.disk_usage(probe).free
        except OSError:
            pass
        required_bytes = planned_size_bytes + int(planned_size_bytes * headroom_ratio)
        return {
            "target_drive": str(target_path.drive or target_path),
            "target_base": str(target_path),
            "free_space_bytes": free_bytes,
            "free_space_gb": round(free_bytes / 1024 / 1024 / 1024, 2),
            "planned_size_bytes": planned_size_bytes,
            "planned_size_gb": round(planned_size_bytes / 1024 / 1024 / 1024, 2),
            "headroom_ratio": headroom_ratio,
            "headroom_required_bytes": required_bytes,
            "headroom_required_gb": round(required_bytes / 1024 / 1024 / 1024, 2),
            "enough_space": free_bytes >= required_bytes,
        }

    @classmethod
    def _load_cleanup_plan(cls) -> dict[str, dict]:
        plan: dict[str, dict] = {}
        if not cls.CLEANUP_PLAN_FILE.exists():
            return plan
        try:
            for line in cls.CLEANUP_PLAN_FILE.read_text(encoding="utf-8").splitlines():
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rj_id = str(entry.get("rj_id") or "").strip().upper()
                if rj_id:
                    plan[rj_id] = entry
        except OSError:
            return {}
        return plan

    @classmethod
    def _append_cleanup_plan(cls, entry: dict) -> None:
        """Atomically upsert one preserved-source entry by RJ id."""
        plan = cls._load_cleanup_plan()
        rj_id = str(entry.get("rj_id") or "").strip().upper()
        if not rj_id:
            raise ValueError("cleanup plan entry requires rj_id")
        entry = dict(entry)
        entry["rj_id"] = rj_id
        plan[rj_id] = entry
        cls.CLEANUP_PLAN_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp_path = cls.CLEANUP_PLAN_FILE.with_name(
            cls.CLEANUP_PLAN_FILE.name + f".{uuid4().hex}.tmp"
        )
        payload = "".join(
            json.dumps(plan[key], ensure_ascii=False, sort_keys=True) + "\n"
            for key in sorted(plan)
        )
        temp_path.write_text(payload, encoding="utf-8")
        os.replace(temp_path, cls.CLEANUP_PLAN_FILE)


    def _table_exists(self, table: str) -> bool:
        try:
            return self.db.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone() is not None
        except Exception:
            return False

    def _rows_for_scan(self):
        return self.db.conn.execute(
            """SELECT w.rj_id, w.title, w.local_path, w.status,
                      COALESCE(w.size_bytes, 0) AS size_bytes,
                      EXISTS (
                          SELECT 1 FROM downloads d
                          WHERE d.rj_id = w.rj_id
                          AND lower(d.status) IN
                              ('queued','paused','downloading','failed','resuming')
                      ) AS has_pending
               FROM works w
               WHERE lower(w.status) IN ('completed','verified')
               ORDER BY w.rj_id"""
        ).fetchall()

    def scan_candidates(self, target_base: str) -> dict:
        """Scan migratable works using real disk manifests, not stale DB sizes."""
        target_path = self._resolve_path(target_base)
        summary = {
            "target_base": str(target_path),
            "candidate_count": 0,
            "total_size_bytes": 0,
            "total_size_mb": 0.0,
            "skipped_already_on_target": 0,
            "skipped_target_exists": 0,
            "skipped_pending": 0,
            "skipped_part_file": 0,
            "skipped_symlink_or_unreadable": 0,
            "db_size_mismatch_count": 0,
            "candidates": [],
        }
        try:
            rows = self._rows_for_scan()
        except Exception as exc:
            logger.error("scan_candidates error: %s", exc)
            summary["error"] = str(exc)
            return summary

        for row in rows:
            source_raw = str(row["local_path"] or "")
            if not source_raw or not os.path.isdir(source_raw):
                continue
            if row["has_pending"]:
                summary["skipped_pending"] += 1
                continue
            if self._is_same_or_under(source_raw, target_path):
                summary["skipped_already_on_target"] += 1
                continue
            source_path = self._resolve_path(source_raw)
            target = target_path / source_path.name
            if target.exists():
                summary["skipped_target_exists"] += 1
                continue
            try:
                manifest = build_migration_manifest(source_path)
            except MigrationManifestError as exc:
                if "partial download" in str(exc):
                    summary["skipped_part_file"] += 1
                else:
                    summary["skipped_symlink_or_unreadable"] += 1
                continue
            db_size = int(row["size_bytes"] or 0)
            if db_size and db_size != manifest.total_bytes:
                summary["db_size_mismatch_count"] += 1
            candidate = {
                "rj_id": row["rj_id"],
                "title": row["title"] or "",
                "source": str(source_path),
                "target": str(target),
                "size_bytes": manifest.total_bytes,
                "db_size_bytes": db_size,
                "size_mb": round(manifest.total_bytes / 1024 / 1024, 1),
                "file_count": manifest.file_count,
                "manifest_token": manifest.token,
                "status": str(row["status"] or "").casefold(),
                "reason": "safe_to_migrate",
            }
            summary["candidates"].append(candidate)
            summary["total_size_bytes"] += manifest.total_bytes

        summary["candidate_count"] = len(summary["candidates"])
        summary["total_size_mb"] = round(summary["total_size_bytes"] / 1024 / 1024, 1)
        return summary

    def get_candidates(self, target_base: str) -> list:
        return self.scan_candidates(target_base)["candidates"]

    def dry_run(self, target_base: str) -> dict:
        dry = self.scan_candidates(target_base)
        dry["space_check"] = self.get_disk_space_check(
            target_base, dry["total_size_bytes"]
        )
        return dry

    def validate_migration_request(
        self,
        rj_id: str,
        source: str,
        target: str,
        target_base: str,
        active_or_queued: Optional[set] = None,
        expected_manifest_token: str = "",
    ) -> dict:
        """Validate a migration request before any destination is created."""
        if active_or_queued and rj_id in active_or_queued:
            return {"success": False, "reason": "active_or_queued"}
        if not self._is_safe_to_move(rj_id):
            return {"success": False, "reason": "pending_downloads"}
        source_path = self._resolve_path(source)
        target_path = self._resolve_path(target)
        target_root = self._resolve_path(target_base)
        if not source_path.is_dir():
            return {"success": False, "reason": "source_missing"}
        if self._is_same_or_under(source_path, target_root):
            return {"success": False, "reason": "source_under_target_base"}
        if not self._is_same_or_under(target_path, target_root):
            return {"success": False, "reason": "target_not_under_target_base"}
        if self._paths_overlap(source_path, target_path):
            return {"success": False, "reason": "source_target_overlap"}
        if target_path.exists():
            return {"success": False, "reason": "target_exists"}
        try:
            manifest = build_migration_manifest(source_path)
        except MigrationManifestError as exc:
            reason = "part_file_present" if "partial download" in str(exc) else "unsafe_source_tree"
            return {"success": False, "reason": reason, "detail": str(exc)}
        if expected_manifest_token and manifest.token != expected_manifest_token:
            return {"success": False, "reason": "source_plan_changed"}
        return {
            "success": True,
            "reason": "",
            "manifest": manifest,
            "manifest_token": manifest.token,
            "size_bytes": manifest.total_bytes,
            "file_count": manifest.file_count,
        }

    def _capture_db_snapshot(self, rj_id: str) -> dict:
        getter = getattr(self.db, "get_external_intake_snapshot", None)
        return getter(rj_id) if callable(getter) else {}

    def _update_db_paths(
        self,
        rj_id: str,
        source: str,
        target: str,
        manifest: MigrationManifest,
        expected_token: str = "",
    ) -> dict:
        updater = getattr(self.db, "update_external_intake_paths", None)
        if callable(updater):
            return updater(
                rj_id,
                source,
                target,
                expected_preimage_token=expected_token,
                file_path_mappings=manifest.file_mappings(target),
            )
        return self.db.move_work_to_path(rj_id, source, target)

    def _reverse_db_paths(
        self,
        rj_id: str,
        source: str,
        target: str,
        manifest: MigrationManifest,
        expected_token: str = "",
    ) -> dict:
        updater = getattr(self.db, "update_external_intake_paths", None)
        if callable(updater):
            reverse_mapping = {
                destination: original
                for original, destination in manifest.file_mappings(target).items()
            }
            return updater(
                rj_id,
                target,
                source,
                expected_preimage_token=expected_token,
                file_path_mappings=reverse_mapping,
            )
        return self.db.move_work_to_path(rj_id, target, source)

    @staticmethod
    def _remove_tree(path: str | Path) -> None:
        if Path(path).exists():
            shutil.rmtree(path)

    def _delete_source_tree(self, path: str) -> None:
        self._remove_tree(path)
        if Path(path).exists():
            raise OSError(f"source still exists after deletion: {path}")

    def migrate_one(
        self,
        rj_id: str,
        source: str,
        target: str,
        delete_source: bool = True,
        target_base: Optional[str] = None,
        active_or_queued: Optional[set] = None,
        expected_manifest_token: str = "",
    ) -> dict:
        """Migrate one work with verified copy, four-table DB update and rollback."""
        _ensure_migration_log_handler()
        target_root = target_base or target
        staging = Path(target).parent / f".{Path(target).name}.migration-{uuid4().hex}.staging"
        result = {
            "rj_id": rj_id,
            "success": False,
            "stage": "safety_check",
            "error": "",
            "error_code": "",
            "delete_source": delete_source,
            "cleanup_required": not delete_source,
            "source_removed": False,
            "target_verified": False,
            "rollback_performed": False,
            "stop_required": False,
            "manifest_token": "",
        }
        logger.info("MIGRATION_START rj=%s source=%s target=%s", rj_id, source, target)

        validation = self.validate_migration_request(
            rj_id,
            source,
            target,
            target_root,
            active_or_queued=active_or_queued,
            expected_manifest_token=expected_manifest_token,
        )
        if not validation["success"]:
            result["error"] = validation["reason"]
            result["error_code"] = validation["reason"]
            logger.error("MIGRATION_REJECT rj=%s reason=%s", rj_id, validation["reason"])
            return result

        manifest: MigrationManifest = validation["manifest"]
        result["manifest_token"] = manifest.token
        preimage = self._capture_db_snapshot(rj_id)
        preimage_token = str(preimage.get("snapshot_token") or "")
        db_updated = False
        db_result: dict = {}

        try:
            result["stage"] = "copy"
            staging.parent.mkdir(parents=True, exist_ok=True)
            file_count, total_bytes = self._copy_dir(source, str(staging))
            logger.info(
                "MIGRATION_COPY_DONE rj=%s files=%s bytes=%s",
                rj_id,
                file_count,
                total_bytes,
            )

            result["stage"] = "verify"
            if not self._verify_dir(source, str(staging), manifest=manifest):
                result["error"] = "verification failed: relative path, size or hash mismatch"
                result["error_code"] = "staging_verification_failed"
                logger.error("MIGRATION_FAIL rj=%s stage=verify error=%s", rj_id, result["error"])
                return result
            logger.info("MIGRATION_VERIFY_DONE rj=%s", rj_id)

            result["stage"] = "commit_target"
            if Path(target).exists():
                result["error"] = "target_exists"
                result["error_code"] = "target_exists"
                return result
            os.replace(staging, target)
            verified, issues = compare_manifest_to_tree(manifest, target)
            if not verified:
                result["error"] = "; ".join(issues[:5])
                result["error_code"] = "target_verification_failed"
                try:
                    self._remove_tree(target)
                    result["rollback_performed"] = not Path(target).exists()
                except OSError as cleanup_exc:
                    result["stop_required"] = True
                    result["error"] += f"; target cleanup failed: {cleanup_exc}"
                return result
            result["target_verified"] = True

            result["stage"] = "db_update"
            db_result = self._update_db_paths(
                rj_id, source, target, manifest, expected_token=preimage_token
            )
            if not db_result.get("success"):
                result["error"] = f"DB update failed: {db_result.get('error')}"
                result["error_code"] = str(db_result.get("error_code") or "db_update_failed")
                try:
                    self._remove_tree(target)
                    result["rollback_performed"] = not Path(target).exists()
                except OSError as cleanup_exc:
                    result["stop_required"] = True
                    result["error"] += f"; target cleanup failed: {cleanup_exc}"
                logger.error("MIGRATION_FAIL rj=%s stage=db_update error=%s", rj_id, result["error"])
                return result
            db_updated = True
            logger.info("MIGRATION_DB_UPDATE_DONE rj=%s", rj_id)

            if delete_source:
                result["stage"] = "delete_source"
                try:
                    self._delete_source_tree(source)
                except Exception as exc:
                    source_intact, source_issues = compare_manifest_to_tree(
                        manifest, source, require_mtime=True
                    )
                    if source_intact:
                        reverse = self._reverse_db_paths(
                            rj_id,
                            source,
                            target,
                            manifest,
                            expected_token=str(db_result.get("postimage_token") or ""),
                        )
                        if reverse.get("success"):
                            try:
                                self._remove_tree(target)
                            except OSError as cleanup_exc:
                                result["stop_required"] = True
                                result["error_code"] = "rollback_target_cleanup_failed"
                                result["error"] = f"{exc}; rollback cleanup failed: {cleanup_exc}"
                                return result
                            result["rollback_performed"] = True
                            result["error_code"] = "source_delete_failed_rolled_back"
                            result["error"] = str(exc)
                            logger.error(
                                "MIGRATION_FAIL rj=%s stage=delete_source error=%s rollback=done",
                                rj_id,
                                exc,
                            )
                            return result
                        result["stop_required"] = True
                        result["error_code"] = "source_delete_failed_db_rollback_failed"
                        result["error"] = f"{exc}; DB rollback failed: {reverse.get('error')}"
                        return result
                    result["stop_required"] = True
                    result["error_code"] = "source_delete_partial_failure"
                    result["error"] = f"{exc}; source changed: {source_issues[:5]}"
                    return result
                result["source_removed"] = not Path(source).exists()
                if not result["source_removed"]:
                    result["stop_required"] = True
                    result["error_code"] = "source_delete_not_confirmed"
                    result["error"] = "source directory still exists"
                    return result
                logger.info("MIGRATION_DELETE_SOURCE_DONE rj=%s", rj_id)
            else:
                result["stage"] = "source_preserved"
                cleanup_entry = {
                    "rj_id": rj_id,
                    "source": source,
                    "target": target,
                    "status": "source_preserved",
                    "migrated_at": datetime.now(timezone.utc).isoformat(),
                    "verified": True,
                    "source_manifest_token": manifest.token,
                    "target_manifest_token": manifest.token,
                    "delete_allowed_after_full_verification": True,
                }
                self._append_cleanup_plan(cleanup_entry)
                logger.info(
                    "MIGRATION_SOURCE_PRESERVED rj=%s source_preserved=True "
                    "cleanup_required=True old_source=%s target=%s",
                    rj_id,
                    source,
                    target,
                )

            result["success"] = True
            logger.info("MIGRATION_DONE rj=%s", rj_id)
            return result
        except Exception as exc:
            result["error"] = str(exc)
            if db_updated:
                result["stop_required"] = True
                result["error_code"] = result["error_code"] or "post_db_failure"
            else:
                result["error_code"] = result["error_code"] or "unexpected_error"
            if not db_updated and Path(target).exists():
                try:
                    self._remove_tree(target)
                    result["rollback_performed"] = True
                except OSError:
                    result["stop_required"] = True
            logger.error(
                "MIGRATION_FAIL rj=%s stage=%s error=%s",
                rj_id,
                result["stage"],
                exc,
            )
            return result
        finally:
            if staging.exists():
                try:
                    self._remove_tree(staging)
                except OSError:
                    result["stop_required"] = True

    def _is_safe_to_move(self, rj_id: str) -> bool:
        safe = self.db.get_safe_migratable_works()
        return any(str(work["rj_id"]) == rj_id for work in safe)

    def verify_migrated_work(
        self,
        rj_id: str,
        target_base: str,
        source_roots: Optional[List[str]] = None,
    ) -> dict:
        """Verify target files plus works/downloads/library_items/library_index."""
        target_base_path = self._resolve_path(target_base)
        row = self.db.conn.execute(
            "SELECT rj_id, local_path, status FROM works WHERE rj_id=?", (rj_id,)
        ).fetchone()
        if not row:
            return {"success": False, "reason": "work_not_found", "rj_id": rj_id}

        work_path = str(row["local_path"] or "")
        work_exists = bool(work_path) and Path(work_path).is_dir()
        work_on_target = bool(work_path) and self._is_same_or_under(work_path, target_base_path)
        part_files_present = bool(work_path) and self._has_part_files(work_path)
        target_manifest = None
        target_manifest_error = ""
        if work_exists:
            try:
                target_manifest = build_migration_manifest(work_path)
            except MigrationManifestError as exc:
                target_manifest_error = str(exc)

        downloads = self.db.conn.execute(
            "SELECT local_path FROM downloads WHERE rj_id=? ORDER BY id", (rj_id,)
        ).fetchall()
        missing_downloads: list[str] = []
        downloads_not_on_target: list[str] = []
        for download in downloads:
            path = str(download["local_path"] or "")
            if not path or not Path(path).is_file():
                missing_downloads.append(path)
            elif not self._is_same_or_under(path, work_path):
                downloads_not_on_target.append(path)

        if self._table_exists("library_items"):
            item_rows = self.db.conn.execute(
                "SELECT folder_path FROM library_items WHERE rj_id=?", (rj_id,)
            ).fetchall()
            library_items_on_target = all(
                self._is_same_or_under(str(item["folder_path"] or ""), target_base_path)
                for item in item_rows
            )
        else:
            item_rows = []
            library_items_on_target = True

        if self._table_exists("library_index"):
            index_rows = self.db.conn.execute(
                "SELECT library_path,work_dir FROM library_index WHERE rj_id=? ORDER BY work_dir",
                (rj_id,),
            ).fetchall()
            library_on_target = all(
                self._is_same_or_under(str(item["work_dir"] or ""), target_base_path)
                for item in index_rows
            )
        else:
            index_rows = []
            library_on_target = True

        cleanup_entry = self._load_cleanup_plan().get(rj_id)
        source_preserved = bool(
            cleanup_entry and cleanup_entry.get("status") == "source_preserved"
        )
        source_details: list[dict] = []
        source_removed_or_empty = True
        preserved_source_ok = not source_preserved
        work_name = Path(work_path).name if work_path else ""
        source_candidates: list[Path] = []
        if source_preserved and cleanup_entry and cleanup_entry.get("source"):
            source_candidates.append(self._resolve_path(cleanup_entry["source"]))
        source_candidates.extend(
            self._resolve_path(root) / work_name for root in (source_roots or [])
        )
        seen_candidates: set[str] = set()
        for candidate in source_candidates:
            candidate_key = os.path.normcase(str(candidate))
            if candidate_key in seen_candidates:
                continue
            seen_candidates.add(candidate_key)
            if candidate == self._resolve_path(work_path):
                continue
            exists = candidate.exists()
            detail = {"path": str(candidate), "exists": exists}
            if exists and candidate.is_dir():
                try:
                    source_manifest = build_migration_manifest(candidate)
                    detail.update(
                        file_count=source_manifest.file_count,
                        total_bytes=source_manifest.total_bytes,
                        manifest_token=source_manifest.token,
                    )
                    if source_preserved and target_manifest:
                        preserved_source_ok = source_manifest.token == target_manifest.token
                    elif not source_preserved:
                        source_removed_or_empty = False
                except MigrationManifestError as exc:
                    detail["error"] = str(exc)
                    if "contains no files" in str(exc):
                        detail.update(file_count=0, total_bytes=0, manifest_token="")
                        if source_preserved:
                            preserved_source_ok = False
                    elif source_preserved:
                        preserved_source_ok = False
                    else:
                        source_removed_or_empty = False
            elif exists:
                source_removed_or_empty = False
            source_details.append(detail)

        if source_preserved and not source_details:
            preserved_source_ok = False

        success = bool(
            work_exists
            and work_on_target
            and target_manifest
            and not target_manifest_error
            and not missing_downloads
            and not downloads_not_on_target
            and not part_files_present
            and library_items_on_target
            and library_on_target
            and (
                (source_preserved and preserved_source_ok)
                or (not source_preserved and source_removed_or_empty)
            )
        )
        return {
            "success": success,
            "rj_id": rj_id,
            "work_path": work_path,
            "work_exists": work_exists,
            "work_on_target": work_on_target,
            "downloads_count": len(downloads),
            "missing_downloads": missing_downloads,
            "downloads_not_on_target": downloads_not_on_target,
            "source_candidates": [detail["path"] for detail in source_details],
            "source_details": source_details,
            "source_removed_or_empty": source_removed_or_empty,
            "source_preserved": source_preserved,
            "cleanup_plan_entry": cleanup_entry,
            "cleanup_plan_present": bool(cleanup_entry),
            "preserved_source_ok": preserved_source_ok,
            "library_on_target": library_on_target,
            "library_items_on_target": library_items_on_target,
            "part_files_present": part_files_present,
            "target_manifest_error": target_manifest_error,
            "target_manifest_token": target_manifest.token if target_manifest else "",
        }

    @staticmethod
    def _copy_dir(src: str, dst: str) -> tuple[int, int]:
        """Copy a source tree without following links. Returns count and bytes."""
        source = Path(src)
        destination = Path(dst)
        if destination.exists():
            raise FileExistsError(f"staging already exists: {destination}")
        destination.mkdir(parents=True)
        file_count = 0
        total_bytes = 0
        for current, dir_names, file_names in os.walk(source, followlinks=False):
            current_path = Path(current)
            relative_dir = current_path.relative_to(source)
            target_dir = destination / relative_dir
            target_dir.mkdir(parents=True, exist_ok=True)
            for name in dir_names:
                directory = current_path / name
                if directory.is_symlink():
                    raise MigrationManifestError(f"symlink directory is not allowed: {directory}")
            for name in file_names:
                file_path = current_path / name
                if file_path.is_symlink():
                    raise MigrationManifestError(f"symlink file is not allowed: {file_path}")
                target_file = target_dir / name
                shutil.copy2(file_path, target_file)
                file_count += 1
                total_bytes += file_path.stat().st_size
        return file_count, total_bytes

    @staticmethod
    def _verify_dir(
        src: str,
        dst: str,
        *,
        manifest: MigrationManifest | None = None,
    ) -> bool:
        """Verify exact relative paths, per-file sizes and recorded hashes."""
        source_manifest = manifest or build_migration_manifest(src)
        verified, _ = compare_manifest_to_tree(source_manifest, dst)
        return verified
