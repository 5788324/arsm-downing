"""RC8: Safe cross-disk migration for completed/verified works.

Two-phase: copy -> verify -> rename -> DB update -> delete source.
All failures roll back. Never touch pending downloads.
"""

import logging
import os
import shutil
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("echovault.migration")


class MigrationEngine:
    """Handles safe migration of completed/verified works between disks."""

    def __init__(self, db):
        self.db = db
        self._migration_log = []

    @staticmethod
    def _resolve_path(path: str) -> Path:
        return Path(path).expanduser().resolve(strict=False)

    @classmethod
    def _is_same_or_under(cls, path: str, base: str) -> bool:
        try:
            path_norm = str(cls._resolve_path(path)).lower()
            base_norm = str(cls._resolve_path(base)).lower()
            return os.path.commonpath([path_norm, base_norm]) == base_norm
        except (ValueError, OSError):
            return False

    @staticmethod
    def _has_part_files(path: str) -> bool:
        try:
            for entry in os.listdir(path):
                full = os.path.join(path, entry)
                if os.path.isfile(full) and entry.endswith('.part'):
                    return True
        except OSError:
            return False
        return False

    def scan_candidates(self, target_base: str) -> dict:
        """Scan migratable works and return candidates plus skip counts."""
        target_path = self._resolve_path(target_base)
        allowed_statuses = {'completed', 'verified'}
        summary = {
            'target_base': str(target_path),
            'candidate_count': 0,
            'total_size_bytes': 0,
            'total_size_mb': 0.0,
            'skipped_already_on_target': 0,
            'skipped_target_exists': 0,
            'skipped_pending': 0,
            'skipped_part_file': 0,
            'candidates': [],
        }
        try:
            rows = self.db.conn.execute(
                """SELECT w.rj_id, w.title, w.local_path, w.status,
                          COALESCE(w.size_bytes, 0) AS size_bytes,
                          EXISTS (
                              SELECT 1 FROM downloads d
                              WHERE d.rj_id = w.rj_id
                              AND d.status IN ('queued','paused','downloading','failed')
                          ) AS has_pending
                   FROM works w
                   WHERE w.status IN
                   ('completed','verified','prepared','partial','failed','paused','external')
                   ORDER BY w.rj_id"""
            ).fetchall()
        except Exception as e:
            logging.error(f"scan_candidates error: {e}")
            return summary

        for row in rows:
            status = (row['status'] or '').lower()
            if status not in allowed_statuses:
                continue

            src = row['local_path'] or ''
            if not src or not os.path.isdir(src):
                continue

            if row['has_pending']:
                summary['skipped_pending'] += 1
                continue

            if self._is_same_or_under(src, str(target_path)):
                summary['skipped_already_on_target'] += 1
                continue

            if self._has_part_files(src):
                summary['skipped_part_file'] += 1
                continue

            src_path = self._resolve_path(src)
            target = str(target_path / src_path.name)
            if os.path.exists(target):
                if not os.path.isdir(target):
                    summary['skipped_target_exists'] += 1
                    continue
                try:
                    if os.listdir(target):
                        summary['skipped_target_exists'] += 1
                        continue
                except OSError:
                    summary['skipped_target_exists'] += 1
                    continue

            size_bytes = row['size_bytes'] or 0
            summary['candidates'].append({
                'rj_id': row['rj_id'],
                'title': row['title'] or '',
                'source': src,
                'target': target,
                'size_bytes': size_bytes,
                'size_mb': round(size_bytes / 1024 / 1024, 1),
                'status': status,
                'reason': 'safe_to_migrate',
            })
            summary['total_size_bytes'] += size_bytes

        summary['candidate_count'] = len(summary['candidates'])
        summary['total_size_mb'] = round(summary['total_size_bytes'] / 1024 / 1024, 1)
        return summary

    def get_candidates(self, target_base: str) -> list:
        """Return works safe to migrate."""
        return self.scan_candidates(target_base)['candidates']

    def dry_run(self, target_base: str) -> dict:
        """Return dry-run stats without modifying anything."""
        return self.scan_candidates(target_base)

    def validate_migration_request(
        self,
        rj_id: str,
        source: str,
        target: str,
        target_base: str,
        active_or_queued: Optional[set] = None,
    ) -> dict:
        """Validate a migration request before touching files."""
        if active_or_queued and rj_id in active_or_queued:
            return {'success': False, 'reason': 'active_or_queued'}
        if not self._is_safe_to_move(rj_id):
            return {'success': False, 'reason': 'pending_downloads'}
        if not source or not os.path.isdir(source):
            return {'success': False, 'reason': 'source_missing'}
        if self._is_same_or_under(source, target_base):
            return {'success': False, 'reason': 'source_under_target_base'}
        if not self._is_same_or_under(target, target_base):
            return {'success': False, 'reason': 'target_not_under_target_base'}
        if self._resolve_path(source) == self._resolve_path(target):
            return {'success': False, 'reason': 'source_equals_target'}
        if self._has_part_files(source):
            return {'success': False, 'reason': 'part_file_present'}
        if os.path.exists(target):
            if not os.path.isdir(target):
                return {'success': False, 'reason': 'target_exists_nonempty'}
            try:
                if os.listdir(target):
                    return {'success': False, 'reason': 'target_exists_nonempty'}
            except OSError:
                return {'success': False, 'reason': 'target_exists_nonempty'}
        return {'success': True, 'reason': ''}

    def migrate_one(
        self,
        rj_id: str,
        source: str,
        target: str,
        target_base: Optional[str] = None,
        active_or_queued: Optional[set] = None,
    ) -> dict:
        """Migrate a single work. Returns dict with success/error/stage."""
        result = {'rj_id': rj_id, 'success': False, 'stage': '', 'error': ''}
        tmp_target = target + '.tmp_migrating'
        logger.info(f"MIGRATION_START rj={rj_id} source={source} target={target}")

        try:
            if target_base is not None:
                validation = self.validate_migration_request(
                    rj_id, source, target, target_base, active_or_queued=active_or_queued)
                if not validation['success']:
                    result['stage'] = 'safety_check'
                    result['error'] = validation['reason']
                    logger.error(f"MIGRATION_REJECT rj={rj_id} reason={validation['reason']}")
                    return result

            if not self._is_safe_to_move(rj_id):
                result['error'] = f"{rj_id} has pending or incomplete downloads"
                result['stage'] = 'safety_check'
                logger.error(f"MIGRATION_FAIL rj={rj_id} stage=safety_check error={result['error']}")
                return result

            if not os.path.exists(source):
                result['error'] = f"source {source} does not exist"
                result['stage'] = 'safety_check'
                logger.error(f"MIGRATION_FAIL rj={rj_id} stage=safety_check error={result['error']}")
                return result

            result['stage'] = 'copy'
            file_count, total_bytes = self._copy_dir(source, tmp_target)
            logger.info(f"MIGRATION_COPY_DONE rj={rj_id} files={file_count} bytes={total_bytes}")

            result['stage'] = 'verify'
            if not self._verify_dir(source, tmp_target):
                shutil.rmtree(tmp_target, ignore_errors=True)
                result['error'] = 'verification failed: file count or size mismatch'
                logger.error(f"MIGRATION_FAIL rj={rj_id} stage=verify error={result['error']}")
                return result
            logger.info(f"MIGRATION_VERIFY_DONE rj={rj_id}")

            result['stage'] = 'rename'
            if os.path.exists(target):
                shutil.rmtree(target, ignore_errors=True)
            os.rename(tmp_target, target)

            result['stage'] = 'db_update'
            db_result = self.db.move_work_to_path(rj_id, source, target)
            if not db_result.get('success'):
                os.rename(target, tmp_target)
                shutil.rmtree(tmp_target, ignore_errors=True)
                result['error'] = f"DB update failed: {db_result.get('error')}"
                logger.error(f"MIGRATION_FAIL rj={rj_id} stage=db_update error={result['error']}")
                return result
            logger.info(f"MIGRATION_DB_UPDATE_DONE rj={rj_id}")

            result['stage'] = 'delete_source'
            shutil.rmtree(source, ignore_errors=True)
            logger.info(f"MIGRATION_DELETE_SOURCE_DONE rj={rj_id}")

            result['success'] = True
            logger.info(f"MIGRATION_DONE rj={rj_id}")
        except Exception as e:
            result['error'] = str(e)
            if os.path.exists(tmp_target):
                shutil.rmtree(tmp_target, ignore_errors=True)
            logger.error(f"MIGRATION_FAIL rj={rj_id} stage={result['stage']} error={e}")

        return result

    def _is_safe_to_move(self, rj_id: str) -> bool:
        """Check work has no pending downloads."""
        safe = self.db.get_safe_migratable_works()
        return any(w['rj_id'] == rj_id for w in safe)

    def verify_migrated_work(
        self,
        rj_id: str,
        target_base: str,
        source_roots: Optional[List[str]] = None,
    ) -> dict:
        """Verify DB/file state for a migrated work."""
        target_base_str = str(self._resolve_path(target_base))
        row = self.db.conn.execute(
            'SELECT rj_id, local_path, status FROM works WHERE rj_id=?',
            (rj_id,),
        ).fetchone()
        if not row:
            return {'success': False, 'reason': 'work_not_found', 'rj_id': rj_id}

        work_path = row['local_path'] or ''
        work_exists = bool(work_path) and os.path.isdir(work_path)
        work_on_target = bool(work_path) and self._is_same_or_under(work_path, target_base_str)

        downloads = self.db.conn.execute(
            'SELECT local_path FROM downloads WHERE rj_id=? ORDER BY id',
            (rj_id,),
        ).fetchall()
        missing_downloads = []
        downloads_not_on_target = []
        for dl in downloads:
            dl_path = dl['local_path'] or ''
            if not dl_path or not os.path.exists(dl_path):
                missing_downloads.append(dl_path)
                continue
            if not (
                self._is_same_or_under(dl_path, target_base_str)
                or (work_path and self._is_same_or_under(dl_path, work_path))
            ):
                downloads_not_on_target.append(dl_path)

        source_candidates = []
        work_name = Path(work_path).name if work_path else ''
        for root in source_roots or []:
            root_resolved = str(self._resolve_path(root))
            if root_resolved.lower() == target_base_str.lower():
                continue
            candidate = str(Path(root_resolved) / work_name)
            if work_path and self._resolve_path(candidate) == self._resolve_path(work_path):
                continue
            source_candidates.append(candidate)

        source_dir_ok = True
        for candidate in source_candidates:
            if os.path.isdir(candidate):
                try:
                    if os.listdir(candidate):
                        source_dir_ok = False
                        break
                except OSError:
                    source_dir_ok = False
                    break
            elif os.path.exists(candidate):
                source_dir_ok = False
                break

        part_files_present = bool(work_path) and self._has_part_files(work_path)
        success = (
            work_exists and work_on_target and not missing_downloads
            and not downloads_not_on_target and source_dir_ok and not part_files_present
        )
        return {
            'success': success,
            'rj_id': rj_id,
            'work_path': work_path,
            'work_exists': work_exists,
            'work_on_target': work_on_target,
            'downloads_count': len(downloads),
            'missing_downloads': missing_downloads,
            'downloads_not_on_target': downloads_not_on_target,
            'source_candidates': source_candidates,
            'source_removed_or_empty': source_dir_ok,
            'part_files_present': part_files_present,
        }

    @staticmethod
    def _copy_dir(src: str, dst: str) -> tuple:
        """Copy directory. Returns (file_count, total_bytes)."""
        os.makedirs(dst, exist_ok=True)
        file_count = 0
        total_bytes = 0
        for root, dirs, files in os.walk(src):
            rel = os.path.relpath(root, src)
            target_dir = os.path.join(dst, rel) if rel != '.' else dst
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
