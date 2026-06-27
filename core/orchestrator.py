import asyncio
import hashlib
import json as _json
import os
import re
import sys
import logging
import urllib.parse
from pathlib import Path
from typing import List, Callable, Optional, Dict

import aiofiles
import aiohttp
import yarl

from core.models import WorkMetadata, TrackItem, SessionStats, ProgressEvent
from core.config import ConfigManager
from core.database import LibraryVault
from core.network import NetworkKernel
from core.audio import AudioProcessor
from core.speed import SpeedTracker
from core.status import WorkStatus

logger = logging.getLogger("echovault")


class Orchestrator:
    """Orchestrates download operations with metadata cache and download state."""

    def __init__(self, kernel: NetworkKernel, config: ConfigManager,
                 db: LibraryVault):
        self.kernel = kernel
        self.config = config
        self.db = db
        self.stats = SessionStats()
        self.speed = SpeedTracker(window_seconds=5.0)
        # ── RC7.6: per-RJ semaphore, NOT global ──
        self._global_inflight = 0
        self._global_inflight_lock = asyncio.Lock()
        self._per_rj_inflight: Dict[str, int] = {}
        self.download_queue: asyncio.Queue = asyncio.Queue()
        self._queued_work_data: Dict[str, dict] = {}  # RC7.7: rj_id→{meta,targets,root_path}
        self.queued_rj_ids: set = set()
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self.cancelled_rjs: set = set()
        self._shutting_down: bool = False
        # ── RC7.8: pause/resume lifecycle ──
        self.global_paused: bool = False
        self.pause_generation: int = 0
        self.on_progress: Optional[Callable] = None
        self.on_work_status: Optional[Callable] = None

    # ── callbacks ──
    def set_callbacks(self, on_progress, on_work_status):
        self.on_progress = on_progress
        self.on_work_status = on_work_status

    def _emit_progress(self, rj_id: str, track_id: str, track_title: str,
                        downloaded: int, total: int, status: str):
        """Emit a structured progress event with speed/eta fields."""
        if not self.on_progress:
            return
        try:
            pct = (downloaded / total * 100) if total > 0 else 0.0
            trk_speed = self.speed.track_speed(rj_id, track_id)
            wrk_speed = self.speed.work_speed(rj_id)
            glb_speed = self.speed.global_speed()
            eta = self.speed.track_eta(rj_id, track_id, downloaded, total)
            event = ProgressEvent(
                rj_id=rj_id,
                track_id=track_id,
                track_title=track_title,
                downloaded_bytes=downloaded,
                total_bytes=total,
                percent=round(pct, 1),
                track_speed_bps=round(trk_speed),
                work_speed_bps=round(wrk_speed),
                global_speed_bps=round(glb_speed),
                eta_seconds=round(eta) if eta is not None else None,
                status=status,
            )
            self.on_progress(event)
        except Exception:
            pass

    def _emit_work_status(self, rj_id, status):
        if self.on_work_status:
            try:
                self.on_work_status(rj_id, status)
            except Exception:
                pass

    # ── stable download ID ──
    @staticmethod
    def _make_dl_id(rj_id: str, track_id: str, save_path: Path,
                    title: str) -> str:
        """Generate a stable, unique download ID."""
        key = f"{rj_id}:{track_id}:{save_path.name}"
        h = hashlib.sha1(key.encode()).hexdigest()[:12]
        return f"{rj_id}:{h}"

    # ── worker loop ──
    async def boot_worker(self):
        while not self._shutting_down:
            try:
                rj_id = await asyncio.wait_for(
                    self.download_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            # ── RC7.8: triple-check before WORKER_START ──

            # Check 1: global_paused
            if self.global_paused:
                logger.info(f"WORKER_SKIP rj={rj_id} reason=global_paused")
                self.queued_rj_ids.discard(rj_id)
                self._queued_work_data.pop(rj_id, None)
                self.download_queue.task_done()
                continue

            # Check 2: still in queued_rj_ids or cancelled
            if rj_id in self.cancelled_rjs:
                self.cancelled_rjs.discard(rj_id)
                self.queued_rj_ids.discard(rj_id)
                self._queued_work_data.pop(rj_id, None)
                logger.info(f"WORKER_SKIP rj={rj_id} reason=cancelled")
                self.download_queue.task_done()
                continue

            if rj_id not in self.queued_rj_ids:
                self._queued_work_data.pop(rj_id, None)
                logger.info(f"WORKER_SKIP rj={rj_id} reason=not_queued")
                self.download_queue.task_done()
                continue

            # Check 3: DB status check
            if not self._is_ready_to_download(rj_id):
                self.queued_rj_ids.discard(rj_id)
                self._queued_work_data.pop(rj_id, None)
                logger.info(f"WORKER_SKIP rj={rj_id} reason=db_status_not_ready")
                self.download_queue.task_done()
                continue

            # ── All checks passed: get work data ──
            work_data = self._queued_work_data.pop(rj_id, None)
            self.queued_rj_ids.discard(rj_id)

            if not work_data:
                logger.warning(f"WORKER_SKIP rj={rj_id} reason=no_work_data")
                self.download_queue.task_done()
                continue

            # ── WORKER_START ──
            self._emit_work_status(rj_id, "Downloading")
            logger.info(
                f"WORKER_START rj={rj_id} "
                f"queued_remaining={len(self.queued_rj_ids)} "
                f"active={len(self.active_tasks)}")
            task = asyncio.create_task(
                self._process_download(rj_id,
                                       work_data["meta"],
                                       work_data["targets"],
                                       work_data["root_path"]))
            self.active_tasks[rj_id] = task
            try:
                await task
            except asyncio.CancelledError:
                logging.info(f"Task {rj_id} cancelled.")
                self._emit_work_status(rj_id, "Paused")
            except Exception as e:
                logging.error(f"Job failed for {rj_id}: {e}", exc_info=True)
                self._emit_work_status(rj_id, f"Error: {e}")
            finally:
                self.active_tasks.pop(rj_id, None)
                self.download_queue.task_done()

    async def boot_workers(self):
        """Start work_concurrency worker tasks."""
        n = max(1, min(self.config.work_concurrency, 4))
        mp = self.config.metadata_proxy or "off"
        dp = self.config.download_proxy or "direct"
        fb = self.config.download_fallback_to_proxy
        logger.info(f"Starting {n} download workers | "
                    f"metadata_proxy={mp} download_proxy={dp} "
                    f"download_fallback_to_proxy={fb}")
        self._log_concurrency_state("boot_workers")
        tasks = [asyncio.create_task(self.boot_worker()) for _ in range(n)]
        return tasks

    def _log_concurrency_state(self, label: str = ""):
        """Diagnostic: log current concurrency / queue state."""
        d_proxy = self.config.get_proxy_for('download') or "direct"
        active_rjs = list(self.active_tasks.keys())
        logger.info(
            f"CONCURRENCY_STATE [{label}] "
            f"work_concurrency={self.config.work_concurrency} "
            f"file_concurrency={self.config.file_concurrency} "
            f"queued_rj_ids={len(self.queued_rj_ids)} "
            f"active_tasks={len(self.active_tasks)} "
            f"active_rjs={active_rjs[:6]} "
            f"download_proxy={d_proxy}")
        # Also log individual worker state
        if active_rjs:
            logger.info(
                f"CONCURRENCY_ACTIVE [{label}] "
                f"downloading_rj_ids={active_rjs}")

    async def pause_job_async(self, rj_id: str):
        """Async-safe pause: runs on background loop."""
        return self.pause_job(rj_id)

    async def shutdown(self):
        """Graceful shutdown: pause all, flush DB, stop workers."""
        self._shutting_down = True
        logger.info("Shutdown: pausing all active tasks")
        self.pause_all()
        # Cancel all active tasks
        for rj_id, task in list(self.active_tasks.items()):
            task.cancel()
        # Wait briefly for cancellations
        await asyncio.sleep(0.5)
        # ── RC7.7: final cleanup ──
        self._queued_work_data.clear()
        # Flush DB
        self.db.commit()
        await self.kernel.shutdown()
        logger.info("Shutdown complete")

    # ══════════════════════════════════════════════
    #  P1.5-5:  pause / resume with DB state
    # ══════════════════════════════════════════════
    def pause_job(self, rj_id):
        """Pause all non-terminal downloads for this rj_id."""
        # Write paused to DB for all tracks that aren't terminal
        rows = self.db.get_downloads_by_rj(rj_id)
        for row in rows:
            if row["status"] not in ('completed', 'registered', 'failed', 'paused', 'stale', 'ignored'):
                self.db.upsert_download(
                    row["id"], rj_id, row["track_title"],
                    row["local_path"], 'paused',
                    row["downloaded_bytes"], row["total_bytes"])

        # Freeze speed meters
        self.speed.pause_work(rj_id)

        # Cancel active task if running
        if rj_id in self.active_tasks:
            self.active_tasks[rj_id].cancel()
        else:
            self.cancelled_rjs.add(rj_id)
        self._emit_work_status(rj_id, "Paused")

    def cancel_job(self, rj_id):
        self.pause_job(rj_id)

    # ══════════════════════════════════════════════
    #  RC1: external metadata enrichment
    # ══════════════════════════════════════════════
    async def enrich_external_works(self, max_concurrent: int = 3):
        """Fetch metadata for external/indexed works missing titles."""
        ext = self.db.get_external_works()
        if not ext:
            return 0
        sem = asyncio.Semaphore(max_concurrent)

        async def _enrich_one(rj_id):
            async with sem:
                cached = self.db.get_metadata_cache(rj_id)
                if cached:
                    self.db.enrich_external_metadata(
                        rj_id, None, cached.get("cover_url", ""),
                        cached.get("title", rj_id), cached.get("circle", ""))
                    return
                rj_num = rj_id[2:]
                meta = await self.kernel.fetch(f"/api/workInfo/{rj_num}")
                if meta:
                    title = meta.get("title", rj_id)
                    circle = meta.get("circle", {}).get("name", "")
                    cover = meta.get("mainCoverUrl", "")
                    self.db.set_metadata_cache(
                        rj_id, title, circle, cover, meta, [])
                    self.db.enrich_external_metadata(
                        rj_id, meta, cover, title, circle)

        tasks = [_enrich_one(row["rj_id"]) for row in ext]
        await asyncio.gather(*tasks)
        return len(tasks)

    async def verify_library_works(self):
        """Verify completeness of all external/partial works."""
        rows = self.db.conn.execute(
            "SELECT rj_id, local_path FROM works "
            "WHERE status IN ('external','indexed','partial','verified')"
        ).fetchall()
        results = {}
        for row in rows:
            cached = self.db.get_metadata_cache(row["rj_id"])
            if cached:
                import json as _j
                tracks = _j.loads(cached.get("tracks_json", "[]"))
                status = self.db.verify_library_item(
                    row["rj_id"], row["local_path"], tracks)
                results[row["rj_id"]] = status
        return results

    def get_track_detail_for_ui(self, rj_id: str, active_tracks: dict = None):
        """Return track details for UI detail dialog. Multi-fallback.

        Returns: list of dicts with title/status/downloaded/total/local_path
        """
        result = []

        # 1. Active downloads in memory
        if active_tracks:
            for title, info in active_tracks.items():
                result.append({
                    "title": title,
                    "status": info.get("status", "pending"),
                    "downloaded": info.get("downloaded", 0),
                    "total": info.get("total", 0),
                    "local_path": "",
                })

        # 2. Fallback to DB downloads table
        if not result:
            rows = self.db.get_downloads_by_rj(rj_id)
            for r in rows:
                result.append({
                    "title": r["track_title"],
                    "status": r["status"],
                    "downloaded": r["downloaded_bytes"],
                    "total": r["total_bytes"],
                    "local_path": r["local_path"],
                })

        # 3. Fallback to metadata_cache
        if not result:
            cached = self.db.get_metadata_cache(rj_id)
            if cached:
                import json as _j
                tracks = _j.loads(cached.get("tracks_json", "[]"))
                for t in tracks:
                    if t.get("type") == "folder":
                        continue
                    result.append({
                        "title": t.get("title", "Unknown"),
                        "status": "pending",
                        "downloaded": 0,
                        "total": t.get("size", 0),
                        "local_path": "",
                    })

        return result

    # ══════════════════════════════════════════════
    #  P3.5: batch controls
    # ══════════════════════════════════════════════
    def _is_ready_to_download(self, rj_id: str) -> bool:
        """Check DB and in-memory state: should this RJ be processed?"""
        # Already being processed → skip
        if rj_id in self.active_tasks:
            return False
        # Cancelled
        if rj_id in self.cancelled_rjs:
            return False
        # Check downloads table for paused/completed
        rows = self.db.get_downloads_by_rj(rj_id)
        # If all downloads are terminal → skip
        all_terminal = all(
            row["status"] in ('completed', 'registered', 'failed', 'stale', 'ignored')
            for row in rows)
        if all_terminal and rows:
            return False
        # If all queued/downloading are now paused → skip
        has_pending = any(
            row["status"] in ('queued', 'downloading')
            for row in rows)
        return has_pending

    def pause_all(self):
        """Pause all pausable works + set global_paused + drain queue (RC7.8)."""
        self.pause_generation += 1
        self.global_paused = True
        gen = self.pause_generation

        queue_before = self.download_queue.qsize()
        queued_before = len(self.queued_rj_ids)
        active_before = len(self.active_tasks)

        logger.info(
            f"PAUSE_ALL_BEGIN generation={gen} "
            f"queue_size={queue_before} queued_rj_ids={queued_before} "
            f"active_tasks={active_before}")

        # 1. Pause all queued/downloading works in DB
        rows = self.db.conn.execute(
            "SELECT DISTINCT rj_id FROM downloads "
            "WHERE status IN ('queued','downloading')").fetchall()
        rj_ids = [row["rj_id"] for row in rows]
        w_rows = self.db.conn.execute(
            "SELECT rj_id FROM works WHERE status='prepared'").fetchall()
        for r in w_rows:
            if r["rj_id"] not in rj_ids:
                rj_ids.append(r["rj_id"])

        for rj_id in rj_ids:
            self.speed.pause_work(rj_id)
            self.pause_job(rj_id)
            self._emit_work_status(rj_id, "Paused")

        # 2. Drain download_queue
        drained = 0
        while not self.download_queue.empty():
            try:
                item = self.download_queue.get_nowait()
                self.download_queue.task_done()
                if isinstance(item, str):
                    self.queued_rj_ids.discard(item)
                drained += 1
            except asyncio.QueueEmpty:
                break

        # 3. Clear work_data + queued_rj_ids
        self._queued_work_data.clear()
        self.queued_rj_ids.clear()

        # 4. Cancel all active tasks
        active_cancelled = 0
        for rj_id, task in list(self.active_tasks.items()):
            if not task.done():
                task.cancel()
                active_cancelled += 1

        logger.info(
            f"PAUSE_ALL_DRAINED queue_drained={drained} "
            f"queued_rj_ids_before={queued_before} active_before={active_before}")

        logger.info(
            f"PAUSE_ALL_CANCELLED active_cancelled={active_cancelled}")

        logger.info(
            f"PAUSE_ALL_DONE generation={gen} "
            f"queue_size={self.download_queue.qsize()} "
            f"queued_rj_ids={len(self.queued_rj_ids)} "
            f"active_tasks={len(self.active_tasks)} "
            f"global_paused={self.global_paused} "
            f"global_inflight={self._global_inflight}")

        return rj_ids

    def resume_all(self):
        """Return paused/queued/failed/partial RJs with pending downloads.

        RC7.10: Classify by status for diagnostic logging.
        Exclude already active/queued.
        """
        rows = self.db.conn.execute(
            "SELECT DISTINCT rj_id, status FROM downloads "
            "WHERE status IN ('paused','queued','failed','downloading','resuming')"
        ).fetchall()

        # Classify by status
        counts = {"paused": 0, "failed": 0, "queued": 0,
                  "downloading": 0, "resuming": 0}
        seen = set()
        for row in rows:
            rj_id = row["rj_id"]
            st = row["status"]
            if rj_id in self.queued_rj_ids or rj_id in self.active_tasks:
                continue
            if rj_id not in seen:
                seen.add(rj_id)
                if st in counts:
                    counts[st] += 1

        result = list(seen)

        # ── RC7.10: Also scan for failed that are resumable/retryable ──
        failed_rj = set()
        retry_from_zero = 0
        resumable = 0
        skipped = 0
        for rj_id in result:
            dl = self.db.get_downloads_summary(rj_id)
            if dl.get("failed", 0) > 0:
                failed_rj.add(rj_id)
                # Check if this failed RJ can be retried (has metadata cache)
                if self.db.get_metadata_cache(rj_id):
                    # Check for partial files
                    has_partial = any(
                        dl.get(s, 0) > 0 for s in ("paused", "downloading"))
                    if has_partial:
                        resumable += 1
                    else:
                        retry_from_zero += 1
                else:
                    skipped += 1

        logger.info(
            f"RESUME_ALL_SCAN paused={counts['paused']} "
            f"failed={counts['failed']} "
            f"registered=0 "
            f"retry_from_zero={retry_from_zero} "
            f"resumable={resumable} "
            f"skipped={skipped}")
        logger.info(f"RESUME_ALL_ENQUEUED count={len(result)}")
        if not result:
            logger.info("RESUME_ALL_NONE reason=no_pending_restorable")
        return result

    async def _resume_one(self, rj_id: str) -> dict:
        """Unified resume for single-task and batch.

        Handles already_queued / already_running guards.
        resume_job emits work_status internally — caller does NOT emit again.
        """
        # Guard against duplicate enqueue
        if rj_id in self.active_tasks:
            return {"status": "already_running", "message": "Already active"}
        if rj_id in self.queued_rj_ids:
            return {"status": "already_queued", "message": "Already in queue"}
        self.speed.resume_work(rj_id)
        result = await self.resume_job(rj_id)
        # resume_job emits Queued / No pending tracks / etc. internally
        return result

    async def _resume_all_async(self):
        """Internal: actually resume all paused/queued works.

        RC7.8: Clear global_paused before resuming.
        """
        # ── RC7.8: reopen for new work ──
        self.global_paused = False
        logger.info(f"RESUME_ALL: global_paused=False generation={self.pause_generation}")

        rj_ids = self.resume_all()
        stats = {
            "resumed_to_queue": 0, "already_queued": 0,
            "already_running": 0, "no_pending": 0,
            "no_cache": 0, "cache_corrupt": 0, "failed": 0,
        }
        logger.info(f"resume_all: starting {len(rj_ids)} works")
        self._log_concurrency_state("resume_all_start")

        for rj_id in rj_ids:
            result = await self._resume_one(rj_id)
            st = result.get("status", "unknown")
            if st == "queued":
                stats["resumed_to_queue"] += 1
            elif st in stats:
                stats[st] += 1
            else:
                stats["failed"] += 1

        logger.info(
            f"resume_all DONE: total={len(rj_ids)} "
            f"resumed_to_queue={stats['resumed_to_queue']} "
            f"already_queued={stats['already_queued']} "
            f"already_running={stats['already_running']} "
            f"no_pending={stats['no_pending']} "
            f"no_cache={stats['no_cache']} "
            f"cache_corrupt={stats['cache_corrupt']} "
            f"failed={stats['failed']}")
        self._log_concurrency_state("resume_all_done")
        return stats

    async def resume_job(self, rj_id: str) -> dict:

    # ══════════════════════════════════════════════
        """Resume paused/queued downloads from DB state."""
        cached = self.db.get_metadata_cache(rj_id)
        if not cached:
            return {"status": "no_cache", "message": "No metadata cache"}

        try:
            meta_raw = _json.loads(cached["metadata_json"])
            tracks_raw = _json.loads(cached["tracks_json"])
        except Exception:
            return {"status": "cache_corrupt", "message": "Corrupt cache"}

        meta = self._build_metadata(rj_id, meta_raw)
        root_path = self.get_save_path(meta)
        hierarchy = self.parse_hierarchy(tracks_raw, root_path, root_path)

        def flatten(nodes):
            result = []
            for n in nodes:
                if n.type != 'folder':
                    result.append(n)
                result.extend(flatten(n.children))
            return result

        all_targets = self.deduplicate_tracks(flatten(hierarchy))

        # Only resume tracks that are paused/queued/downloading
        db_states = {
            row["id"]: dict(row)
            for row in self.db.get_downloads_by_rj(rj_id)
        }
        resume_targets = []
        for t in all_targets:
            dl_id = self._make_dl_id(rj_id, t.id or t.title,
                                     t.save_path, t.title)
            st = db_states.get(dl_id, {})
            status = st.get("status", "queued") if st else "queued"
            if status in ('paused', 'queued', 'downloading'):
                resume_targets.append(t)

        if not resume_targets:
            self._emit_work_status(rj_id, "No pending tracks")
            return {"status": "no_pending",
                    "message": "No pending tracks to resume"}

        self._emit_work_status(rj_id, "Resuming...")
        for t in resume_targets:
            dl_id = self._make_dl_id(rj_id, t.id or t.title,
                                     t.save_path, t.title)
            self.db.upsert_download(dl_id, rj_id, t.title,
                                    str(t.save_path), 'queued',
                                    t.save_path.stat().st_size
                                    if t.save_path.exists() else 0,
                                    t.size)
            self._emit_progress(rj_id, t.id or t.title, t.title,
                                t.save_path.stat().st_size
                                if t.save_path.exists() else 0,
                                t.size, "pending")

        # ── RC7.7: store only rj_id + work_data, NOT coroutine ──
        self._queued_work_data[rj_id] = {
            "meta": meta, "targets": resume_targets,
            "root_path": root_path}
        await self.download_queue.put(rj_id)
        self.queued_rj_ids.add(rj_id)
        # ── RC7.4: emit "Queued" here — worker emits "Downloading" later ──
        self._emit_work_status(rj_id, "Queued")
        return {"status": "queued", "message": "Queued for download",
                "count": len(resume_targets)}

    # ══════════════════════════════════════════════
    #  P1.5-2:  restore on startup
    # ══════════════════════════════════════════════
    async def restore_pending_downloads(self):
        """Cold-start: normalize ONLY interrupted active states → paused.

        downloading/resuming → paused (interrupted, cannot persist across restart).
        queued → kept as queued (user explicitly queued, should not be lost).
        paused → kept as paused.
        """
        pending = self.db.get_pending_downloads()
        if not pending:
            return

        auto_resume = getattr(self.config, 'auto_resume_on_start', False)
        normalized_downloads = 0
        normalized_works = set()

        rj_groups: Dict[str, set] = {}
        for row in pending:
            rj_groups.setdefault(row["rj_id"], set()).add(row["status"])

        paused_rj_ids = []

        for rj_id in sorted(rj_groups):
            statuses = rj_groups[rj_id]

            # Only normalize truly interrupted states (downloading/resuming).
            # queued and paused stay as-is.
            for row in pending:
                if row["rj_id"] != rj_id:
                    continue
                if row["status"] in ('downloading', 'resuming'):
                    self.db.upsert_download(
                        row["id"], rj_id, row["track_title"],
                        row["local_path"], 'paused',
                        row["downloaded_bytes"], row["total_bytes"])
                    normalized_downloads += 1
                    normalized_works.add(rj_id)

            if self.db.get_metadata_cache(rj_id):
                paused_rj_ids.append(rj_id)
            else:
                logger.warning(f"Skip restore {rj_id}: no metadata cache")

        # ── RC7.9: normalize works.status for interrupted works ──
        for rj_id in normalized_works:
            ws = self.db.get_works_status(rj_id)
            if ws in ('queued', 'downloading', 'resuming'):
                self.db.execute_write(
                    "UPDATE works SET status='paused' WHERE rj_id=?", (rj_id,))
            elif ws == 'prepared':
                # prepared but interrupted → mark so UI knows it's restorable
                pass

        logger.info(
            f"STARTUP_PASSIVE_MODE auto_resume={auto_resume} "
            f"normalized_downloads={normalized_downloads} "
            f"normalized_works={len(normalized_works)}")
        logger.info(
            f"restore_pending: {len(paused_rj_ids)} restorable RJs "
            f"(auto_resume={auto_resume}, enqueued=0)")

        # ── RC7.9: only enqueue when explicitly auto_resume=True ──
        if not auto_resume:
            # Do NOT enqueue anything. UI will show paused status.
            return

        # Auto-resume: limit to work_concurrency
        async def _delayed_resume():
            await asyncio.sleep(0.5)
            limit = self.config.work_concurrency
            for i, rj_id in enumerate(paused_rj_ids):
                if i >= limit:
                    break
                await self._resume_one(rj_id)

        if paused_rj_ids:
            asyncio.create_task(_delayed_resume())

    # ── utilities ──
    @staticmethod
    def sanitize(name: str) -> str:
        name = name.strip(". ")
        name = re.sub(r'[<>:"/\\|?*]', '_', name)
        name = re.sub(r'[\x00-\x1f]', '', name)
        name = re.sub(r'_+', '_', name)
        name = ' '.join(name.split())
        return name[:200] if name else "Unknown"

    @staticmethod
    def deduplicate_tracks(targets: List[TrackItem]) -> List[TrackItem]:
        seen: Dict[str, int] = {}
        for t in targets:
            key = str(t.save_path)
            if key in seen:
                seen[key] += 1
                t.save_path = t.save_path.parent / \
                    f"{t.save_path.stem}_{seen[key]}{t.save_path.suffix}"
                t.title = f"{t.title}_{seen[key]}"
            else:
                seen[key] = 1
        return targets

    def get_save_path(self, meta: WorkMetadata) -> Path:
        ctx = {
            "rj_id": meta.rj_id,
            "title": self.sanitize(meta.title),
            "circle": self.sanitize(meta.circle),
            "year": meta.release_date[:4] if meta.release_date else ""
        }
        try:
            folder = self.config.dir_template.format(**ctx)
        except KeyError:
            folder = f"{meta.rj_id} {self.sanitize(meta.title)}"
        return self.config.output_dir / folder

    def categorize_path(self, root, filename, ftype):
        if not self.config.sort_files:
            return root / filename
        ext = Path(filename).suffix.lower()
        if ftype == 'audio' or ext in ['.mp3','.wav','.flac','.m4a','.ogg','.aac','.wma']:
            return root / "Audio" / filename
        elif ftype == 'image' or ext in ['.jpg','.jpeg','.png','.webp','.gif','.bmp']:
            return root / "Images" / filename
        elif ftype == 'text' or ext in ['.txt','.pdf','.doc','.docx','.html']:
            return root / "Text" / filename
        return root / "Other" / filename

    def parse_hierarchy(self, data, root_path, base_path, level=0):
        items = []
        for node in data:
            title = self.sanitize(node.get("title", "Unknown"))
            if node.get("type") == "folder":
                item = TrackItem(id="dir", title=title, type="folder",
                                 url="", size=0,
                                 save_path=root_path / title, level=level)
                item.children = self.parse_hierarchy(
                    node.get("children", []), root_path / title,
                    base_path, level + 1)
                items.append(item)
            elif "mediaDownloadUrl" in node:
                save_path = (self.categorize_path(base_path, title, node.get("type", "file"))
                             if self.config.sort_files else root_path / title)
                raw_url = node["mediaDownloadUrl"]
                pu = urllib.parse.urlsplit(raw_url)
                safe = urllib.parse.quote(urllib.parse.unquote(pu.path))
                fixed = urllib.parse.urlunsplit(
                    (pu.scheme, pu.netloc, safe, pu.query, pu.fragment))
                items.append(TrackItem(
                    id=str(node.get("id", "")), title=title,
                    type=node.get("type", "file"),
                    url=str(yarl.URL(fixed, encoded=True)),
                    size=node.get("size", 0),
                    save_path=save_path, level=level))
        return items

    @staticmethod
    def _build_metadata(rj_id: str, meta_raw: dict) -> WorkMetadata:
        return WorkMetadata(
            rj_id=rj_id,
            title=meta_raw.get('title', 'Unknown'),
            circle=meta_raw.get('circle', {}).get('name', 'Unknown'),
            cv=[v.get('name', '') for v in meta_raw.get('vas', [])],
            tags=[t.get('name', '') for t in meta_raw.get('tags', [])],
            price=meta_raw.get('price', 0),
            source_url=meta_raw.get('source_url', ''),
            dl_count=meta_raw.get('dl_count', 0),
            rating=meta_raw.get('rate_average_2dp', 0.0),
            release_date=meta_raw.get('release_date', ''),
            cover_url=meta_raw.get('mainCoverUrl', '')
        )

    # ══════════════════════════════════════════════
    #  P1-1: Metadata cache integration
    # ══════════════════════════════════════════════
    async def _fetch_metadata_live(self, rj_id: str, rj_numeric: str):
        meta_raw = await self.kernel.fetch(f"/api/workInfo/{rj_numeric}")
        if not meta_raw:
            return None, None
        tracks_raw = await self.kernel.fetch(f"/api/tracks/{rj_numeric}?v=2")
        if not tracks_raw:
            return meta_raw, None
        circle_name = meta_raw.get('circle', {}).get('name', 'Unknown')
        self.db.set_metadata_cache(
            rj_id=rj_id, title=meta_raw.get('title', ''),
            circle=circle_name,
            cover_url=meta_raw.get('mainCoverUrl', ''),
            metadata_raw=meta_raw, tracks_raw=tracks_raw)
        return meta_raw, tracks_raw

    # ══════════════════════════════════════════════
    #  P3.2: prepare_work — separate metadata from download
    # ══════════════════════════════════════════════
    async def prepare_work(self, rj_id: str, force_refresh: bool = False,
                            allow_duplicate: bool = False):
        """Fetch metadata, create folder, write DB state. No download.

        Returns:
            (meta, targets, root_path, from_cache) or (None, None, None, False)
        """
        self._emit_work_status(rj_id, "Preparing")
        if not rj_id.upper().startswith("RJ"):
            rj_id = f"RJ{rj_id}"
        rj_numeric = rj_id[2:]

        # ── RC1: core-level duplicate guard ──
        if not allow_duplicate:
            dup = self.db.find_in_library(rj_id)
            if dup:
                paths = [d["work_dir"] for d in dup[:3]]
                self._emit_work_status(
                    rj_id, f"Duplicate: {', '.join(paths)}")
                return None, None, None, False

        meta_raw = None
        tracks_raw = None
        from_cache = False

        if not force_refresh:
            cached = self.db.get_metadata_cache(rj_id)
            if cached:
                try:
                    meta_raw = _json.loads(cached["metadata_json"])
                    tracks_raw = _json.loads(cached["tracks_json"])
                    from_cache = True
                    logging.info(f"Metadata cache HIT for {rj_id}")
                except Exception:
                    try:
                        self.db.invalidate_cache(rj_id)
                    except Exception:
                        pass

        if meta_raw is None:
            try:
                meta_raw, tracks_raw = await self._fetch_metadata_live(
                    rj_id, rj_numeric)
            except Exception as e:
                logger.error(f"Metadata fetch failed for {rj_id}: {e}")
                store = self.db.conn.execute(
                    "SELECT rj_id FROM works WHERE rj_id=?", (rj_id,)
                ).fetchone()
                if not store:
                    from core.models import WorkMetadata
                    self.db.register(
                        WorkMetadata(rj_id=rj_id, title=rj_id, circle="",
                                     cv=[], tags=[], price=0, source_url="",
                                     dl_count=0, rating=0.0, release_date="",
                                     cover_url=""),
                        0, Path("."), status='metadata_failed')
                else:
                    self.db.execute_write(
                        "UPDATE works SET status='metadata_failed' WHERE rj_id=?",
                        (rj_id,))
                self._emit_work_status(
                    rj_id,
                    f"Metadata failed: proxy {self.config.metadata_proxy or self.config.proxy or 'off'}"
                )
                return None, None, None, False
            if not meta_raw:
                self._emit_work_status(rj_id, "Failed to fetch metadata")
                return None, None, None, False

        if tracks_raw is None:
            self._emit_work_status(rj_id, "Failed to fetch tracks")
            return None, None, None, False

        meta = self._build_metadata(rj_id, meta_raw)
        root_path = self.get_save_path(meta)

        # Create folder on disk now
        try:
            root_path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logging.error(f"mkdir failed for {root_path}: {e}")

        # Write works as 'prepared'
        self.db.register(meta, 0, root_path, status='prepared')

        hierarchy = self.parse_hierarchy(tracks_raw, root_path, root_path)

        def flatten(nodes):
            result = []
            for n in nodes:
                if n.type != 'folder':
                    result.append(n)
                result.extend(flatten(n.children))
            return result

        targets = flatten(hierarchy)
        targets = self.deduplicate_tracks(targets)
        if not targets:
            self._emit_work_status(rj_id, "No tracks found")
            return None, None, None, False

        # Write downloads as queued
        for t in targets:
            dl_id = self._make_dl_id(rj_id, t.id or t.title,
                                     t.save_path, t.title)
            existing_size = t.save_path.stat().st_size \
                if t.save_path.exists() else 0
            self.db.upsert_download(
                dl_id, rj_id, t.title, str(t.save_path),
                status='completed' if existing_size == t.size > 0 else 'queued',
                downloaded_bytes=existing_size, total_bytes=t.size)
            self._emit_progress(rj_id, t.id or t.title, t.title,
                                existing_size, t.size, "pending")

        status_msg = "Prepared (cached)" if from_cache else "Prepared"
        logger.info(f"prepare_work {rj_id}: {status_msg}, {len(targets)} tracks")
        self._emit_work_status(rj_id, status_msg)
        return meta, targets, root_path, from_cache

    # ══════════════════════════════════════════════
    #  queue_job — uses prepare_work then downloads
    # ══════════════════════════════════════════════
    async def queue_job(self, rj_id: str, force_refresh: bool = False) -> None:
        meta, targets, root_path, from_cache = await self.prepare_work(
            rj_id, force_refresh)
        if meta is None:
            return

        status_msg = "Queued (cached)" if from_cache else "Queued"
        self._emit_work_status(rj_id, status_msg)
        # ── RC7.7: store only rj_id + work_data, NOT coroutine ──
        self._queued_work_data[rj_id] = {
            "meta": meta, "targets": targets,
            "root_path": root_path}
        self.queued_rj_ids.add(rj_id)
        await self.download_queue.put(rj_id)

    # ══════════════════════════════════════════════
    #  download_file — returns bool
    # ══════════════════════════════════════════════
    async def download_file(self, track: TrackItem, meta: WorkMetadata,
                            cover_path: Optional[Path],
                            file_sem: asyncio.Semaphore) -> bool:
        """Download a single file. Returns True on success/skip, False on failure."""
        final_path = track.save_path
        part_path = final_path.with_suffix(final_path.suffix + ".part")
        dl_id = self._make_dl_id(meta.rj_id, track.id or track.title,
                                 track.save_path, track.title)

        if sys.platform == "win32" and len(str(final_path.absolute())) > 255:
            stem = self.sanitize(track.title)[:30]
            final_path = final_path.parent / f"{stem}{final_path.suffix}"
            part_path = final_path.with_suffix(final_path.suffix + ".part")
            track.save_path = final_path

        try:
            final_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logging.error(f"mkdir failed for {final_path}: {e}")
            self.stats.failed += 1
            self.db.upsert_download(dl_id, meta.rj_id, track.title,
                                    str(final_path), 'failed', error=str(e))
            self._emit_progress(meta.rj_id, track.id or track.title, track.title, 0, track.size, "failed")
            return False

        if final_path.exists() and final_path.stat().st_size == track.size:
            self.stats.skipped += 1
            self.db.upsert_download(dl_id, meta.rj_id, track.title,
                                    str(final_path), 'completed',
                                    track.size, track.size)
            self._emit_progress(meta.rj_id, track.id or track.title, track.title, track.size, track.size, "completed")
            if part_path.exists():
                try: part_path.unlink()
                except OSError: pass
            return True

        existing_size = 0
        if part_path.exists():
            existing_size = part_path.stat().st_size
            if existing_size > track.size:
                existing_size = 0
                try: part_path.unlink()
                except OSError: pass
        elif final_path.exists():
            existing_size = final_path.stat().st_size
            if existing_size > track.size:
                existing_size = 0

        for attempt in range(self.config.retry_count):
            self.db.upsert_download(dl_id, meta.rj_id, track.title,
                                    str(final_path), 'downloading',
                                    existing_size, track.size)
            self._emit_progress(meta.rj_id, track.id or track.title, track.title, existing_size, track.size, "downloading")
            # ── RC3.1: per-attempt diag (moved inside semaphore RC7.6) ──
            is_resume = existing_size > 0
            rng = f"bytes={existing_size}-" if existing_size else "none"
            d_proxy = self.config.get_proxy_for('download') or "direct"
            try:
                headers = {}
                if existing_size > 0:
                    headers["Range"] = f"bytes={existing_size}-"

                # ── RC7.6/RC7.7: per-RJ file slot with try/finally ──
                async with file_sem:
                    # Track in-flight
                    async with self._global_inflight_lock:
                        self._global_inflight += 1
                        global_inflight = self._global_inflight
                    self._per_rj_inflight[meta.rj_id] = \
                        self._per_rj_inflight.get(meta.rj_id, 0) + 1
                    work_inflight = self._per_rj_inflight[meta.rj_id]

                    try:
                        import urllib.parse as _up
                        host = _up.urlparse(track.url).hostname or "unknown"
                        is_resume = existing_size > 0
                        logger.info(
                            f"FILE_SLOT_ACQUIRE rj={meta.rj_id} "
                            f"track={track.title[:50]} "
                            f"host={host} size={track.size} resume={is_resume} "
                            f"work_inflight={work_inflight} global_inflight={global_inflight} "
                            f"file_concurrency={self.config.file_concurrency} "
                            f"work_concurrency={self.config.work_concurrency}")
                        logger.info(
                            f"DOWNLOAD_START rj={meta.rj_id} track={track.title[:50]} "
                            f"host={host} size={track.size} exist={is_resume} "
                            f"path={final_path}")
                        logger.info(
                            f"DOWNLOAD_ATTEMPT rj={meta.rj_id} track={track.title[:40]} "
                            f"attempt={attempt+1}/{self.config.retry_count} "
                            f"resume={is_resume} range={rng} download_proxy={d_proxy}")

                        success, resp_or_err = await self._stream_with_fallback(
                            track.url, headers)

                        if not success:
                            last_attempt = attempt == self.config.retry_count - 1
                            if last_attempt:
                                self.stats.failed += 1
                                self.db.upsert_download(
                                    dl_id, meta.rj_id, track.title,
                                    str(final_path), 'failed',
                                    error=str(resp_or_err))
                                self._emit_progress(meta.rj_id, track.id or track.title, track.title,
                                                    existing_size, track.size, "failed")
                                return False
                            existing_size = 0
                            await asyncio.sleep(
                                    self.config.retry_backoff ** attempt)
                            continue

                        resp = resp_or_err
                        try:
                            if resp.status == 416:
                                self.stats.skipped += 1
                                self.db.upsert_download(
                                    dl_id, meta.rj_id, track.title,
                                    str(final_path), 'completed', track.size, track.size)
                                return True

                            if resp.status not in (200, 206):
                                last_attempt = attempt == self.config.retry_count - 1
                                if last_attempt:
                                    self.stats.failed += 1
                                    self.db.upsert_download(
                                        dl_id, meta.rj_id, track.title,
                                        str(final_path), 'failed',
                                        error=f"HTTP {resp.status}")
                                    self._emit_progress(meta.rj_id, track.id or track.title, track.title,
                                                        existing_size, track.size, "failed")
                                    return False
                                existing_size = 0
                                await asyncio.sleep(
                                    self.config.retry_backoff ** attempt)
                                continue

                            is_partial = resp.status == 206
                            clen = resp.headers.get("Content-Length", "?")
                            cr = resp.headers.get("Content-Range", "none")
                            logger.info(
                                f"DOWNLOAD_RESP rj={meta.rj_id} track={track.title[:40]} "
                                f"http={resp.status} partial={is_partial} "
                                f"content_len={clen} content_range={cr}")
                            if is_partial:
                                cr = resp.headers.get("Content-Range", "")
                                m = re.match(r"bytes\s+(\d+)-\d+/(\d+)", cr)
                                if m and int(m.group(1)) != existing_size:
                                    logging.warning(f"Range mismatch {track.title}")
                                    existing_size = 0
                                    is_partial = False

                            mode = "ab" if is_partial else "wb"
                            target = part_path
                            if resp.status == 200:
                                existing_size = 0
                                mode = "wb"
                            downloaded = existing_size if is_partial else 0
                            completed_ok = False

                            async with aiofiles.open(target, mode) as f:
                                async for chunk in resp.content.iter_chunked(
                                    self.config.chunk_size):
                                    await f.write(chunk)
                                    downloaded += len(chunk)
                                    self.stats.bytes_downloaded += len(chunk)
                                    self.speed.update(
                                        meta.rj_id, track.id or track.title,
                                        downloaded, len(chunk))
                                    self._emit_progress(
                                        meta.rj_id, track.id or track.title, track.title,
                                        downloaded, track.size, "downloading")

                            completed_ok = target.exists() and target.stat().st_size == track.size
                        finally:
                            if not resp.closed:
                                resp.close()

                            if not target.exists():
                                continue

                            actual = target.stat().st_size
                            if actual != track.size:
                                logging.warning(f"Size mismatch {track.title}: {actual} vs {track.size}")
                                if not completed_ok:
                                    continue

                            if target == part_path and part_path.exists():
                                os.replace(str(part_path), str(final_path))

                            if self.config.tag_audio and track.type == 'audio':
                                try:
                                    AudioProcessor.apply_tags(final_path, meta, cover_path)
                                except Exception as e:
                                    logging.warning(f"Tagging failed {final_path}: {e}")

                            self.stats.success += 1
                            self.db.upsert_download(dl_id, meta.rj_id, track.title,
                                                    str(final_path), 'completed',
                                                    track.size, track.size)
                            self._emit_progress(meta.rj_id, track.id or track.title, track.title,
                                                track.size, track.size, "completed")
                    finally:
                        # ── RC7.7: ALWAYS release (even on CancelledError) ──
                        self._per_rj_inflight[meta.rj_id] = max(
                            0, self._per_rj_inflight.get(meta.rj_id, 1) - 1)
                        work_inflight_after = self._per_rj_inflight.get(meta.rj_id, 0)
                        async with self._global_inflight_lock:
                            self._global_inflight = max(0, self._global_inflight - 1)
                            global_inflight_after = self._global_inflight
                        logger.info(
                            f"FILE_SLOT_RELEASE rj={meta.rj_id} "
                            f"track={track.title[:50]} "
                            f"work_inflight={work_inflight_after} "
                            f"global_inflight={global_inflight_after}")

                    return True

            except asyncio.CancelledError:
                self.speed.pause_track(meta.rj_id, track.id or track.title)
                self.db.upsert_download(dl_id, meta.rj_id, track.title,
                                        str(final_path), 'paused',
                                        existing_size, track.size)
                raise
            except Exception as e:
                last_attempt = attempt == self.config.retry_count - 1
                if last_attempt:
                    self.stats.failed += 1
                    # ── RC7.10: keep partial file as paused for resume ──
                    partial_exists = (part_path.exists() and part_path.stat().st_size > 0
                                      ) or (final_path.exists() and final_path.stat().st_size > 0
                                            and final_path.stat().st_size < track.size)
                    final_status = 'paused' if partial_exists else 'failed'
                    self.db.upsert_download(dl_id, meta.rj_id, track.title,
                                            str(final_path), final_status,
                                            error=str(e))
                    self._emit_progress(meta.rj_id, track.id or track.title, track.title,
                                        existing_size if partial_exists else 0,
                                        track.size, "paused" if partial_exists else "failed")
                    logging.warning(
                        f"Download {track.title} {final_status} "
                        f"(partial_file={partial_exists}): {e}")
                    return False
                logging.warning(f"Retry {attempt+1}/3 for {track.title}: {e}")
                existing_size = 0
                await asyncio.sleep(
                                self.config.retry_backoff ** attempt)

        return False

    # ══════════════════════════════════════════════
    #  P1.5-3:  download fallback to proxy
    # ══════════════════════════════════════════════
    async def _stream_with_fallback(self, url: str, headers: dict):
        """Stream with fallback: direct → proxy on failure."""
        # Try direct first (purpose='download' = no proxy unless configured)
        direct_error = None
        dproxy = self.config.get_proxy_for('download') or "direct"
        try:
            resp = await self.kernel.stream(url, headers, purpose='download')
            return True, resp
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
            direct_error = e

        import urllib.parse as _up
        host = _up.urlparse(url).hostname or "?"
        logger.info(f"DOWNLOAD_DIRECT_FAIL host={host} proxy={dproxy} err={direct_error}")

        if not self.config.download_fallback_to_proxy:
            return False, f"Direct failed, fallback disabled: {direct_error}"

        fallback_proxy = (self.config.download_proxy or
                          self.config.metadata_proxy or
                          self.config.proxy)
        if not fallback_proxy:
            return False, f"Direct failed, no proxy configured: {direct_error}"

        logger.info(f"DOWNLOAD_FALLBACK host={host} proxy={fallback_proxy}")
        try:
            await self.kernel.boot()
            resp = await self.kernel.session.get(
                url, headers=headers, proxy=fallback_proxy)
            return True, resp
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
            return False, f"Fallback also failed: {e}"

    # ══════════════════════════════════════════════
    #  P1.5-4:  _process_download with result tracking
    # ══════════════════════════════════════════════
    async def _process_download(self, rj_id: str, meta: WorkMetadata,
                                 targets: List[TrackItem],
                                 root_path: Path) -> None:
        cover_path: Optional[Path] = root_path / "cover.jpg"
        if meta.cover_url:
            root_path.mkdir(parents=True, exist_ok=True)
            try:
                async def fetch_cover():
                    async with await self.kernel.stream(
                        meta.cover_url, purpose='cover'
                    ) as resp:
                        if resp.status == 200:
                            cover_path.write_bytes(await resp.read())
                await asyncio.wait_for(fetch_cover(), timeout=10.0)
            except asyncio.TimeoutError:
                logging.warning(f"Cover timeout for {rj_id}")
                cover_path = None
            except Exception as e:
                # Try direct if proxy failed
                logging.warning(f"Cover proxy failed: {e}, trying direct")
                try:
                    async def fetch_cover_direct():
                        async with await self.kernel.stream(
                            meta.cover_url, purpose='download'
                        ) as resp:
                            if resp.status == 200:
                                cover_path.write_bytes(await resp.read())
                    await asyncio.wait_for(fetch_cover_direct(), timeout=10.0)
                except Exception:
                    logging.warning(
                        f"Cover direct also failed for {rj_id}")
                    cover_path = None
        else:
            cover_path = None

        self._emit_work_status(rj_id, "Downloading")

        # ── RC7.6: per-RJ semaphore (file_concurrency files per work) ──
        file_sem = asyncio.Semaphore(self.config.file_concurrency)
        self._per_rj_inflight[rj_id] = 0

        # Gather with return_exceptions to capture CancelledError
        results = await asyncio.gather(
            *[self.download_file(t, meta, cover_path, file_sem)
              for t in targets],
            return_exceptions=True
        )

        # Clean up in-flight tracking
        self._per_rj_inflight.pop(rj_id, None)

        # Analyze results
        success_count = 0
        failed_count = 0
        cancelled_count = 0
        for r in results:
            if r is True:
                success_count += 1
            elif isinstance(r, asyncio.CancelledError):
                cancelled_count += 1
                failed_count += 1
            else:
                failed_count += 1

        total = len(targets)
        logging.info(f"Download results for {rj_id}: "
                     f"{success_count}/{total} success, {failed_count} failed")

        try:
            if failed_count == 0 and cancelled_count == 0:
                # All success — register work as completed
                final_size = sum(
                    t.save_path.stat().st_size
                    for t in targets if t.save_path.exists())
                self.db.register(meta, final_size, root_path, status='completed')
                for t in targets:
                    dl_id = self._make_dl_id(
                        rj_id, t.id or t.title, t.save_path, t.title)
                    self.db.upsert_download(
                        dl_id, rj_id, t.title, str(t.save_path),
                        'registered', t.size, t.size)
                self._emit_work_status(rj_id, "Completed")
            elif cancelled_count > 0:
                # Was paused — leave paused tracks in DB, don't overwrite
                self._emit_work_status(rj_id, "Paused (partial)")
            else:
                # Some failed — register as partial, do NOT overwrite failed
                self._emit_work_status(
                    rj_id, f"Partially completed ({success_count}/{total})")
                success_targets = [
                    t for i, t in enumerate(targets)
                    if results[i] is True]
                if success_targets:
                    final_size = sum(
                        t.save_path.stat().st_size
                        for t in success_targets if t.save_path.exists())
                    self.db.register(meta, final_size, root_path,
                                     status='partial')
                    for t in success_targets:
                        dl_id = self._make_dl_id(
                            rj_id, t.id or t.title, t.save_path, t.title)
                        self.db.upsert_download(
                            dl_id, rj_id, t.title, str(t.save_path),
                            'registered', t.size, t.size)
        except Exception as e:
            logging.error(f"Failed to register work {rj_id}: {e}")
