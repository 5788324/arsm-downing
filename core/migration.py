"""RC8: Safe cross-disk migration for completed/verified works.

Two-phase: copy → verify → rename → DB update → delete source.
All failures roll back. Never touch pending downloads.
"""

import logging
import os
import shutil
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger("echovault.migration")


class MigrationEngine:
    """Handles safe migration of completed/verified works between disks."""

    def __init__(self, db):
        self.db = db
        self._migration_log = []

    def get_candidates(self, target_base: str) -> list:
        """Return works safe to migrate. Each dict has rj_id, title, source,
        target, size_bytes, status, reason."""
        safe = self.db.get_safe_migratable_works()
        candidates = []
        for w in safe:
            src = w.get("local_path", "")
            if not src or not os.path.exists(src):
                continue
            # Build target path preserving relative structure
            src_path = Path(src)
            target = str(Path(target_base) / src_path.name)
            # Skip if target already exists and is non-empty
            if os.path.exists(target) and os.listdir(target):
                continue
            size_mb = (w.get("size_bytes", 0) or 0) / 1024 / 1024
            # Check for .part files
            has_part = any(
                f.endswith(".part") for f in os.listdir(src)
                if os.path.isfile(os.path.join(src, f)))
            if has_part:
                continue
            candidates.append({
                "rj_id": w["rj_id"],
                "title": w.get("title", ""),
                "source": src,
                "target": target,
                "size_bytes": w.get("size_bytes", 0),
                "size_mb": round(size_mb, 1),
                "status": w.get("status", ""),
                "reason": "safe_to_migrate",
            })
        return candidates

    def dry_run(self, target_base: str) -> dict:
        """Return dry-run stats without modifying anything."""
        candidates = self.get_candidates(target_base)
        total_size = sum(c["size_bytes"] for c in candidates)
        return {
            "candidate_count": len(candidates),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / 1024 / 1024, 1),
            "candidates": candidates,
        }

    def migrate_one(self, rj_id: str, source: str, target: str) -> dict:
        """Migrate a single work. Returns dict with success/error/stage."""
        result = {"rj_id": rj_id, "success": False, "stage": "", "error": ""}
        tmp_target = target + ".tmp_migrating"
        logger.info(f"MIGRATION_START rj={rj_id} source={source} target={target}")

        try:
            # Safety: refuse if work has pending downloads
            if not self._is_safe_to_move(rj_id):
                result["error"] = f"{rj_id} has pending or incomplete downloads"
                result["stage"] = "safety_check"
                logger.error(f"MIGRATION_FAIL rj={rj_id} stage=safety_check error={result['error']}")
                return result

            # Safety: refuse if source doesn't exist
            if not os.path.exists(source):
                result["error"] = f"source {source} does not exist"
                result["stage"] = "safety_check"
                logger.error(f"MIGRATION_FAIL rj={rj_id} stage=safety_check error={result['error']}")
                return result

            # Phase 1: Copy
            result["stage"] = "copy"
            file_count, total_bytes = self._copy_dir(source, tmp_target)
            logger.info(f"MIGRATION_COPY_DONE rj={rj_id} files={file_count} bytes={total_bytes}")

            # Phase 2: Verify
            result["stage"] = "verify"
            if not self._verify_dir(source, tmp_target):
                shutil.rmtree(tmp_target, ignore_errors=True)
                result["error"] = "verification failed: file count or size mismatch"
                logger.error(f"MIGRATION_FAIL rj={rj_id} stage=verify error={result['error']}")
                return result
            logger.info(f"MIGRATION_VERIFY_DONE rj={rj_id}")

            # Phase 3: Rename tmp → target
            result["stage"] = "rename"
            if os.path.exists(target):
                shutil.rmtree(target, ignore_errors=True)
            os.rename(tmp_target, target)

            # Phase 4: Update DB
            result["stage"] = "db_update"
            db_result = self.db.move_work_to_path(rj_id, source, target)
            if not db_result.get("success"):
                # Rollback: move target back
                os.rename(target, tmp_target)
                shutil.rmtree(tmp_target, ignore_errors=True)
                result["error"] = f"DB update failed: {db_result.get('error')}"
                logger.error(f"MIGRATION_FAIL rj={rj_id} stage=db_update error={result['error']}")
                return result
            logger.info(f"MIGRATION_DB_UPDATE_DONE rj={rj_id}")

            # Phase 5: Delete source
            result["stage"] = "delete_source"
            shutil.rmtree(source, ignore_errors=True)
            logger.info(f"MIGRATION_DELETE_SOURCE_DONE rj={rj_id}")

            result["success"] = True
            logger.info(f"MIGRATION_DONE rj={rj_id}")
        except Exception as e:
            result["error"] = str(e)
            # Cleanup tmp target
            if os.path.exists(tmp_target):
                shutil.rmtree(tmp_target, ignore_errors=True)
            logger.error(f"MIGRATION_FAIL rj={rj_id} stage={result['stage']} error={e}")

        return result

    def _is_safe_to_move(self, rj_id: str) -> bool:
        """Check work has no pending downloads."""
        safe = self.db.get_safe_migratable_works()
        return any(w["rj_id"] == rj_id for w in safe)

    @staticmethod
    def _copy_dir(src: str, dst: str) -> tuple:
        """Copy directory. Returns (file_count, total_bytes)."""
        os.makedirs(dst, exist_ok=True)
        file_count = 0
        total_bytes = 0
        for root, dirs, files in os.walk(src):
            rel = os.path.relpath(root, src)
            target_dir = os.path.join(dst, rel) if rel != "." else dst
            os.makedirs(target_dir, exist_ok=True)
            for f in files:
                s = os.path.join(root, f)
                t = os.path.join(target_dir, f)
                shutil.copy2(s, t)
                file_count += 1
                total_bytes += os.path.getsize(s)
        return file_count, total_bytes

    @staticmethod
    def _verify_dir(src: str, dst: str) -> bool:
        """Verify dst matches src: same file count and total size."""
        def count_dir(path):
            fc, tb = 0, 0
            for root, dirs, files in os.walk(path):
                fc += len(files)
                for f in files:
                    tb += os.path.getsize(os.path.join(root, f))
            return fc, tb
        s_fc, s_tb = count_dir(src)
        d_fc, d_tb = count_dir(dst)
        return s_fc == d_fc and s_tb == d_tb
