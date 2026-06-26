"""RC8: Safe cross-disk migration for completed/verified works.

Two-phase: copy -> verify -> rename -> DB update -> delete source.
All failures roll back. Never touch pending downloads.
"""

import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("echovault.migration")


def _ensure_migration_log_handler() -> None:
    """Attach a dedicated migration.log file handler once."""
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
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
        logger.addHandler(file_handler)
        if logger.level == logging.NOTSET or logger.level > logging.INFO:
            logger.setLevel(logging.INFO)
    except OSError:
        pass


_ensure_migration_log_handler()


class MigrationEngine:
    """Handles safe migration of completed/verified works between disks."""

    CLEANUP_PLAN_FILE = Path("logs/migration_cleanup_plan.jsonl")

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

    @classmethod
    def _dir_stats(cls, path: str) -> tuple:
        """Return (file_count, total_bytes) for a directory tree."""
        file_count = 0
        total_bytes = 0
        for root, dirs, files in os.walk(path):
            file_count += len(files)
            for file_name in files:
                try:
                    total_bytes += os.path.getsize(os.path.join(root, file_name))
                except OSError:
                    continue
        return file_count, total_bytes

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
        if target_path.exists():
            try:
                free_bytes = shutil.disk_usage(target_path).free
            except OSError:
                free_bytes = 0
        required_bytes = planned_size_bytes + int(planned_size_bytes * headroom_ratio)
        return {
            'target_drive': str(target_path.drive or target_path),
            'target_base': str(target_path),
            'free_space_bytes': free_bytes,
            'free_space_gb': round(free_bytes / 1024 / 1024 / 1024, 2),
            'planned_size_bytes': planned_size_bytes,
            'planned_size_gb': round(planned_size_bytes / 1024 / 1024 / 1024, 2),
            'headroom_ratio': headroom_ratio,
            'headroom_required_bytes': required_bytes,
            'headroom_required_gb': round(required_bytes / 1024 / 1024 / 1024, 2),
            'enough_space': free_bytes >= required_bytes,
        }

    @classmethod
    def _load_cleanup_plan(cls) -> dict:
        """Return cleanup-plan entries keyed by RJ id."""
        plan = {}
        if not cls.CLEANUP_PLAN_FILE.exists():
            return plan
        try:
            with open(cls.CLEANUP_PLAN_FILE, 'r', encoding='utf-8') as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    rj_id = entry.get('rj_id')
                    if rj_id:
                        plan[rj_id] = entry
        except OSError:
            return plan
        return plan

    @classmethod
    def _append_cleanup_plan(cls, entry: dict) -> None:
        """Append one preserved-source entry to the cleanup plan."""
        cls.CLEANUP_PLAN_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(cls.CLEANUP_PLAN_FILE, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + '\n')

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
        dry = self.scan_candidates(target_base)
        dry['space_check'] = self.get_disk_space_check(
            target_base,
            dry['total_size_bytes'],
        )
        return dry

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
        delete_source: bool = True,
        target_base: Optional[str] = None,
        active_or_queued: Optional[set] = None,
    ) -> dict:
        """Migrate a single work. Returns dict with success/error/stage."""
        result = {
            'rj_id': rj_id,
            'success': False,
            'stage': '',
            'error': '',
            'delete_source': delete_source,
            'cleanup_required': not delete_source,
        }
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

            if delete_source:
                result['stage'] = 'delete_source'
                shutil.rmtree(source, ignore_errors=True)
                logger.info(f"MIGRATION_DELETE_SOURCE_DONE rj={rj_id}")
            else:
                result['stage'] = 'source_preserved'
                cleanup_entry = {
                    'rj_id': rj_id,
                    'source': source,
                    'target': target,
                    'status': 'source_preserved',
                    'migrated_at': datetime.now().isoformat(),
                    'verified': True,
                    'delete_allowed_after_full_verification': True,
                }
                self._append_cleanup_plan(cleanup_entry)
                logger.info(
                    'MIGRATION_SOURCE_PRESERVED '
                    f'rj={rj_id} source_preserved=True cleanup_required=True '
                    f'old_source={source} target={target}'
                )

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

        cleanup_entry = self._load_cleanup_plan().get(rj_id)
        source_preserved = bool(cleanup_entry and cleanup_entry.get('status') == 'source_preserved')
        source_dir_ok = True
        source_details = []
        for candidate in source_candidates:
            if os.path.isdir(candidate):
                file_count, total_bytes = self._dir_stats(candidate)
                source_details.append({
                    'path': candidate,
                    'exists': True,
                    'file_count': file_count,
                    'total_bytes': total_bytes,
                })
                if not source_preserved and file_count > 0:
                    source_dir_ok = False
                    break
            elif os.path.exists(candidate):
                source_details.append({
                    'path': candidate,
                    'exists': True,
                    'file_count': None,
                    'total_bytes': None,
                })
                if not source_preserved:
                    source_dir_ok = False
                    break
            else:
                source_details.append({
                    'path': candidate,
                    'exists': False,
                    'file_count': 0,
                    'total_bytes': 0,
                })

        part_files_present = bool(work_path) and self._has_part_files(work_path)
        target_file_count, target_total_bytes = (0, 0)
        if work_exists:
            target_file_count, target_total_bytes = self._dir_stats(work_path)

        preserved_source_ok = True
        if source_preserved:
            preserved_source_ok = False
            for detail in source_details:
                if detail['exists'] and detail['file_count'] is not None:
                    if detail['file_count'] == target_file_count and detail['total_bytes'] == target_total_bytes:
                        preserved_source_ok = True
                        break
            if not source_details:
                preserved_source_ok = False

        library_rows = self.db.conn.execute(
            'SELECT library_path, work_dir FROM library_index WHERE rj_id=? ORDER BY work_dir',
            (rj_id,),
        ).fetchall()
        library_target_rows = []
        library_non_target_rows = []
        for row_item in library_rows:
            work_dir = row_item['work_dir'] or ''
            if work_dir and self._is_same_or_under(work_dir, target_base_str):
                library_target_rows.append(dict(row_item))
            else:
                library_non_target_rows.append(dict(row_item))
        if source_preserved:
            library_on_target = bool(library_target_rows)
        else:
            library_on_target = bool(library_rows) and not library_non_target_rows

        success = (
            work_exists and work_on_target and not missing_downloads
            and not downloads_not_on_target and not part_files_present
            and library_on_target
            and ((source_preserved and preserved_source_ok) or (not source_preserved and source_dir_ok))
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
            'source_details': source_details,
            'source_removed_or_empty': source_dir_ok,
            'source_preserved': source_preserved,
            'cleanup_plan_entry': cleanup_entry,
            'cleanup_plan_present': bool(cleanup_entry),
            'preserved_source_ok': preserved_source_ok,
            'library_on_target': library_on_target,
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
        s_fc, s_tb = MigrationEngine._dir_stats(src)
        d_fc, d_tb = MigrationEngine._dir_stats(dst)
        return s_fc == d_fc and s_tb == d_tb
