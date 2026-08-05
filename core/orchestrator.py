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
from core.download_response import local_partial_size, plan_download_response
from core.metadata_scheduler import MetadataScheduler
from core.download_workers import DownloadWorkerPool
from core.download_errors import SignedUrlExpired
from core.url_refresh import SignedUrlRefresher

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
        self.metadata_scheduler = MetadataScheduler(
            getattr(config, "metadata_concurrency", 2)
        )
        self.download_queue: asyncio.Queue = asyncio.Queue()
        self._queued_work_data: Dict[str, dict] = {}  # RC7.7: rj_id→{meta,targets,root_path}
        self.queued_rj_ids: set = set()
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self.worker_tasks: List[asyncio.Task] = []
        # Legacy queue-invalidation marker used by pause.
        self.cancelled_rjs: set = set()
        # True user cancellation marker; never set by pause.
        self.user_cancelled_rjs: set = set()
        # In-flight guards close rapid duplicate-click races.
        self.preparing_rj_ids: set = set()
        self.resuming_rj_ids: set = set()
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
                durable_cancel = (
                    rj_id in self.user_cancelled_rjs or
                    (self.db.get_works_status(rj_id) or "").lower() == "cancelled"
                )
                self._emit_work_status(
                    rj_id, "Cancelled" if durable_cancel else "Paused"
                )
            except Exception as e:
                logging.error(f"Job failed for {rj_id}: {e}", exc_info=True)
                self._emit_work_status(rj_id, f"Error: {e}")
            finally:
                self.active_tasks.pop(rj_id, None)
                self.download_queue.task_done()

    async def boot_workers(self):
        """Start independent metadata workers and download workers."""
        await self.metadata_scheduler.start()
        n = max(1, min(self.config.work_concurrency, 4))
        mp = self.config.metadata_proxy or "off"
        dp = self.config.download_proxy or "direct"
        fb = self.config.download_fallback_to_proxy
        logger.info(f"Starting {n} download workers | "
                    f"metadata_proxy={mp} download_proxy={dp} "
                    f"download_fallback_to_proxy={fb}")
        self._log_concurrency_state("boot_workers")
        self.worker_tasks = [
            asyncio.create_task(self.boot_worker(), name=f"arsm-worker-{index+1}")
            for index in range(n)
        ]
        return list(self.worker_tasks)

    def _log_concurrency_state(self, label: str = ""):
        """Diagnostic: log current concurrency / queue state."""
        d_proxy = self.config.get_proxy_for('download') or "direct"
        active_rjs = list(self.active_tasks.keys())
        logger.info(
            f"CONCURRENCY_STATE [{label}] "
            f"work_concurrency={self.config.work_concurrency} "
            f"metadata_concurrency={self.metadata_scheduler.concurrency} "
            f"metadata_queued={self.metadata_scheduler.queued_count} "
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
        """Graceful shutdown: pause work, await cancellation, flush, and close HTTP."""
        if self._shutting_down:
            return
        self._shutting_down = True
        logger.info("Shutdown: pausing all active tasks")
        self.pause_all()

        active = list(dict.fromkeys(self.active_tasks.values()))
        for task in active:
            task.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)

        workers = [task for task in self.worker_tasks if not task.done()]
        for task in workers:
            task.cancel()
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)
        self.worker_tasks.clear()

        self._queued_work_data.clear()
        self.queued_rj_ids.clear()
        await self.metadata_scheduler.shutdown()
        self.db.commit()
        await self.kernel.shutdown()
        logger.info("Shutdown complete")

    # ══════════════════════════════════════════════
    #  P1.5-5:  pause / resume with DB state
    # ══════════════════════════════════════════════
    def pause_job(self, rj_id):
        """Pause all non-terminal downloads and persist a resumable work state."""
        rows = self.db.get_downloads_by_rj(rj_id)
        changed = 0
        for row in rows:
            if str(row["status"] or "").lower() not in {
                "completed", "registered", "failed", "paused", "stale",
                "ignored", "cancelled",
            }:
                self.db.upsert_download(
                    row["id"], rj_id, row["track_title"],
                    row["local_path"], "paused",
                    row["downloaded_bytes"], row["total_bytes"],
                )
                changed += 1
        work_status = (self.db.get_works_status(rj_id) or "").lower()
        if work_status and work_status not in {
            "completed", "registered", "verified", "external", "indexed", "cancelled",
        }:
            self.db.execute_write(
                "UPDATE works SET status='paused' WHERE rj_id=?", (rj_id,)
            )
        self.speed.pause_work(rj_id)
        if rj_id in self.active_tasks:
            self.active_tasks[rj_id].cancel()
        else:
            self.cancelled_rjs.add(rj_id)
        self._emit_work_status(rj_id, "Paused")
        return {"status": "paused", "changed": changed}

    def cancel_job(self, rj_id):
        """Persist a true cancellation while preserving completed and partial files."""
        rows = self.db.get_downloads_by_rj(rj_id)
        work_status = (self.db.get_works_status(rj_id) or "").lower()
        terminal = {"completed", "registered", "verified", "external", "indexed"}
        non_terminal_rows = [
            row for row in rows
            if str(row["status"] or "").lower() not in
            {"completed", "registered", "stale", "ignored", "cancelled"}
        ]
        if work_status in terminal and not non_terminal_rows:
            return {"status": "already_terminal", "changed": 0, "preserved_bytes": 0}

        changed = 0
        preserved_bytes = 0
        for row in non_terminal_rows:
            final_path = Path(row["local_path"])
            part_path = final_path.with_suffix(final_path.suffix + ".part")
            actual = local_partial_size(
                final_path, part_path, int(row["total_bytes"] or 0)
            )
            preserved_bytes += actual
            self.db.upsert_download(
                row["id"], rj_id, row["track_title"], row["local_path"],
                "cancelled", actual, row["total_bytes"],
                error="Cancelled by user; partial data preserved",
            )
            changed += 1

        if work_status or rows:
            self.db.execute_write(
                "UPDATE works SET status='cancelled' WHERE rj_id=?", (rj_id,)
            )
        self.speed.pause_work(rj_id)
        self.user_cancelled_rjs.add(rj_id)
        self.cancelled_rjs.add(rj_id)
        self.queued_rj_ids.discard(rj_id)
        self._queued_work_data.pop(rj_id, None)
        task = self.active_tasks.get(rj_id)
        if task is not None and not task.done():
            task.cancel()
        self._emit_work_status(rj_id, "Cancelled")
        logger.info(
            "CANCEL_JOB rj=%s changed=%s preserved_bytes=%s",
            rj_id, changed, preserved_bytes,
        )
        return {
            "status": "cancelled",
            "changed": changed,
            "preserved_bytes": preserved_bytes,
        }

    async def retry_cancelled_job(self, rj_id: str) -> dict:
        """Explicitly re-enable a cancelled job, preserving its existing partials."""
        rows = self.db.get_downloads_by_rj(rj_id)
        work_cancelled = (self.db.get_works_status(rj_id) or "").lower() == "cancelled"
        changed = 0
        for row in rows:
            if str(row["status"] or "").lower() != "cancelled":
                continue
            self.db.upsert_download(
                row["id"], rj_id, row["track_title"], row["local_path"],
                "failed", row["downloaded_bytes"], row["total_bytes"],
                error="Explicit retry after cancellation",
            )
            changed += 1
        if not changed and not work_cancelled:
            return {"status": "no_pending", "message": "No cancelled files"}
        if work_cancelled:
            self.db.execute_write(
                "UPDATE works SET status='partial' WHERE rj_id=?", (rj_id,)
            )
        self.user_cancelled_rjs.discard(rj_id)
        self.cancelled_rjs.discard(rj_id)
        return await self._resume_one(rj_id)

    async def reconnect_job(self, rj_id: str) -> dict:
        """Pause an active job, wait for cancellation, then resume in order."""
        self.pause_job(rj_id)
        for _ in range(100):
            if rj_id not in self.active_tasks:
                break
            await asyncio.sleep(0.05)
        if rj_id in self.active_tasks:
            return {"status": "pause_timeout",
                    "message": "Timed out waiting for the active task to pause"}
        return await self._resume_one(rj_id)

    # ══════════════════════════════════════════════
    #  RC1: external metadata enrichment
    # ══════════════════════════════════════════════
    async def enrich_external_works(self, max_concurrent: int = 3):
        """Fetch metadata for external/indexed works missing titles."""
        ext = self.db.get_external_works()
        if not ext:
            return 0
        async def _enrich_one(rj_id):
            cached = self.db.get_metadata_cache(rj_id)
            if cached:
                self.db.enrich_external_metadata(
                    rj_id, None, cached.get("cover_url", ""),
                    cached.get("title", rj_id), cached.get("circle", ""))
                return

            async def _fetch():
                rj_num = self._numeric_rj_id(rj_id)
                return await self.kernel.fetch(f"/api/workInfo/{rj_num}")

            meta = await self.metadata_scheduler.submit(
                f"enrich:{rj_id}", _fetch
            )
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
            cached = self.db.get_metadata_cache(
                row["rj_id"], allow_stale=True)
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
            cached = self.db.get_metadata_cache(rj_id, allow_stale=True)
            if cached:
                import json as _j
                tracks = _j.loads(cached.get("tracks_json", "[]"))

                def append_tracks(nodes):
                    for track in nodes or []:
                        if track.get("type") == "folder":
                            append_tracks(track.get("children", []))
                            continue
                        result.append({
                            "title": track.get("title", "Unknown"),
                            "status": "pending",
                            "downloaded": 0,
                            "total": track.get("size", 0),
                            "local_path": "",
                        })

                append_tracks(tracks)

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
            row["status"] in ('completed', 'registered', 'failed', 'stale', 'ignored', 'cancelled')
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
            if (rj_id in self.queued_rj_ids or rj_id in self.active_tasks
                    or rj_id in self.preparing_rj_ids
                    or rj_id in self.resuming_rj_ids):
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
                if self.db.get_metadata_cache(rj_id, allow_stale=True):
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
        """Unified resume for single-task, batch and tray actions.

        ``resuming_rj_ids`` closes the double-click race while metadata is being
        refreshed.  The check-and-add sequence runs without an intervening await on
        the single orchestrator event loop.
        """
        if rj_id in self.active_tasks:
            return {"status": "already_running", "message": "Already active"}
        if rj_id in self.queued_rj_ids or rj_id in self.resuming_rj_ids:
            return {"status": "already_queued", "message": "Already in queue or resuming"}
        work_status = (self.db.get_works_status(rj_id) or "").lower()
        if work_status == "cancelled" or rj_id in self.user_cancelled_rjs:
            return {
                "status": "cancelled",
                "message": "Cancelled tasks require an explicit retry action",
                "skipped_cancelled": 1,
            }
        self.resuming_rj_ids.add(rj_id)
        try:
            self.cancelled_rjs.discard(rj_id)
            self.speed.resume_work(rj_id)
            return await self.resume_job(rj_id)
        finally:
            self.resuming_rj_ids.discard(rj_id)

    async def _resume_all_async(self):
        """Resume every restorable work and aggregate truthful recovery results."""
        self.global_paused = False
        logger.info(
            "RESUME_ALL: global_paused=False generation=%s", self.pause_generation
        )
        rj_ids = self.resume_all()
        stats = {
            "resumed_to_queue": 0,
            "resumed_partial": 0,
            "retried_from_zero": 0,
            "already_complete": 0,
            "metadata_required": 0,
            "unrecoverable": 0,
            "skipped_cancelled": 0,
            "paused_during_resume": 0,
            "already_queued": 0,
            "already_running": 0,
            "no_pending": 0,
            "cache_corrupt": 0,
            "failed": 0,
        }
        logger.info("resume_all: starting %s works", len(rj_ids))
        self._log_concurrency_state("resume_all_start")
        for rj_id in rj_ids:
            try:
                result = await self._resume_one(rj_id)
            except Exception:
                logger.exception("resume_all failed for %s", rj_id)
                stats["failed"] += 1
                continue
            status = result.get("status", "unknown")
            if status == "queued":
                stats["resumed_to_queue"] += 1
            elif status in {
                "already_queued", "already_running", "no_pending",
                "cache_corrupt", "failed",
            }:
                stats[status] += 1
            elif status == "paused":
                stats["paused_during_resume"] += 1
            elif status not in {
                "reconciled_complete", "metadata_required", "cancelled", "unrecoverable",
            }:
                stats["failed"] += 1
            for key in (
                "resumed_partial", "retried_from_zero", "already_complete",
                "metadata_required", "unrecoverable", "skipped_cancelled",
            ):
                stats[key] += int(result.get(key, 0) or 0)
        logger.info("resume_all DONE: %s", stats)
        self._log_concurrency_state("resume_all_done")
        return stats

    async def resume_job(self, rj_id: str) -> dict:
        """Reconcile disk/SQLite state and queue every genuinely restorable file."""
        summary = {
            "resumed_partial": 0,
            "retried_from_zero": 0,
            "already_complete": 0,
            "metadata_required": 0,
            "unrecoverable": 0,
            "skipped_cancelled": 0,
        }
        cached = self.db.get_metadata_cache(rj_id, allow_stale=True)
        prepared_payload = None
        if not cached:
            logger.warning("Resume %s requires metadata refresh", rj_id)
            prepared_payload = await self.prepare_work(
                rj_id, force_refresh=True, allow_duplicate=True
            )
            if not prepared_payload or prepared_payload[0] is None:
                summary["metadata_required"] = 1
                self._emit_work_status(rj_id, "Metadata required")
                return {
                    "status": "metadata_required",
                    "message": "Metadata refresh is required before retry",
                    **summary,
                }

        if prepared_payload:
            meta, all_targets, root_path, _from_cache = prepared_payload
        else:
            if cached.get("is_stale"):
                logger.warning("Resume %s using expired metadata cache", rj_id)
            try:
                meta_raw = _json.loads(cached["metadata_json"])
                tracks_raw = _json.loads(cached["tracks_json"])
            except Exception:
                prepared_payload = await self.prepare_work(
                    rj_id, force_refresh=True, allow_duplicate=True
                )
                if not prepared_payload or prepared_payload[0] is None:
                    summary["metadata_required"] = 1
                    self._emit_work_status(rj_id, "Metadata required")
                    return {
                        "status": "metadata_required",
                        "message": "Metadata cache is corrupt and refresh failed",
                        **summary,
                    }
                meta, all_targets, root_path, _from_cache = prepared_payload
            else:
                meta = self._build_metadata(rj_id, meta_raw)
                root_path = self.get_save_path(meta)
                hierarchy = self.parse_hierarchy(tracks_raw, root_path, root_path)

                def flatten(nodes):
                    result = []
                    for node in nodes:
                        if node.type != 'folder':
                            result.append(node)
                        result.extend(flatten(node.children))
                    return result

                all_targets = self.deduplicate_tracks(flatten(hierarchy))

        # A user can pause/cancel while a metadata refresh is awaiting I/O.  Recheck
        # after every preparation path so a completed refresh never resurrects it.
        if rj_id in self.user_cancelled_rjs:
            result = self.cancel_job(rj_id)
            summary["skipped_cancelled"] = 1
            return {**result, **summary, "during_resume_prepare": True}
        if rj_id in self.cancelled_rjs:
            result = self.pause_job(rj_id)
            return {**result, **summary, "during_resume_prepare": True}

        db_states = {
            row["id"]: dict(row) for row in self.db.get_downloads_by_rj(rj_id)
        }
        resume_targets = []
        for target in all_targets:
            dl_id = self._make_dl_id(
                rj_id, target.id or target.title, target.save_path, target.title
            )
            row = db_states.get(dl_id, {})
            status = str(row.get("status", "queued") or "queued").lower()
            final_path = Path(row.get("local_path") or target.save_path)
            target.save_path = final_path
            part_path = final_path.with_suffix(final_path.suffix + ".part")
            expected = int(target.size or row.get("total_bytes", 0) or 0)

            if status in {"stale", "ignored"}:
                continue
            if status == "cancelled":
                summary["skipped_cancelled"] += 1
                continue

            try:
                final_size = final_path.stat().st_size if final_path.exists() else 0
                part_size = part_path.stat().st_size if part_path.exists() else 0
            except OSError as exc:
                summary["unrecoverable"] += 1
                self.db.upsert_download(
                    dl_id, rj_id, target.title, str(final_path), "failed",
                    int(row.get("downloaded_bytes", 0) or 0), expected,
                    error=f"Unable to inspect partial file: {exc}",
                )
                continue

            # Never trust a terminal SQLite label without checking the actual file.
            # Missing or truncated completed/registered files are repaired using the
            # same partial/zero-byte policy as failed rows.
            if status in {"completed", "registered"}:
                if final_size > 0 and (expected <= 0 or final_size == expected):
                    summary["already_complete"] += 1
                    if part_path.exists():
                        try:
                            part_path.unlink()
                        except OSError:
                            pass
                    continue
                status = "failed"

            if expected > 0 and (final_size > expected or part_size > expected):
                summary["unrecoverable"] += 1
                self.db.upsert_download(
                    dl_id, rj_id, target.title, str(final_path), "failed",
                    max(final_size, part_size), expected,
                    error="Local file is larger than expected; manual review required",
                )
                continue

            if expected > 0 and final_size == expected:
                self.db.upsert_download(
                    dl_id, rj_id, target.title, str(final_path), "completed",
                    expected, expected,
                )
                if part_path.exists():
                    try:
                        part_path.unlink()
                    except OSError:
                        pass
                summary["already_complete"] += 1
                continue

            if expected > 0 and part_size == expected:
                try:
                    final_path.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(str(part_path), str(final_path))
                except OSError as exc:
                    summary["unrecoverable"] += 1
                    self.db.upsert_download(
                        dl_id, rj_id, target.title, str(final_path), "failed",
                        part_size, expected,
                        error=f"Unable to finalize complete partial file: {exc}",
                    )
                    continue
                self.db.upsert_download(
                    dl_id, rj_id, target.title, str(final_path), "completed",
                    expected, expected,
                )
                summary["already_complete"] += 1
                continue

            actual = max(part_size, final_size)
            if actual > 0:
                summary["resumed_partial"] += 1
            elif status == "failed":
                summary["retried_from_zero"] += 1

            if status in {
                "paused", "queued", "downloading", "resuming", "failed",
                "partial", "prepared", "no_pending", "metadata_failed",
            } or not row:
                self.db.upsert_download(
                    dl_id, rj_id, target.title, str(final_path), "queued",
                    actual, expected,
                )
                self._emit_progress(
                    rj_id, target.id or target.title, target.title,
                    actual, expected, "pending",
                )
                resume_targets.append(target)
            else:
                summary["unrecoverable"] += 1

        if not resume_targets:
            if (summary["already_complete"] and not summary["unrecoverable"]
                    and not summary["skipped_cancelled"]):
                self.db.execute_write(
                    "UPDATE works SET status='completed' WHERE rj_id=?", (rj_id,)
                )
                self._emit_work_status(rj_id, "Completed")
                return {
                    "status": "reconciled_complete",
                    "message": "All files were already complete",
                    **summary,
                }
            if summary["unrecoverable"]:
                self._emit_work_status(rj_id, "Failed: manual review required")
                return {
                    "status": "unrecoverable",
                    "message": "One or more local files require manual review",
                    **summary,
                }
            self._emit_work_status(rj_id, "No pending tracks")
            return {
                "status": "no_pending",
                "message": "No pending tracks to resume",
                **summary,
            }

        self.cancelled_rjs.discard(rj_id)
        self._emit_work_status(rj_id, "Resuming...")
        self.db.execute_write(
            "UPDATE works SET status='queued' WHERE rj_id=?", (rj_id,)
        )
        self._queued_work_data[rj_id] = {
            "meta": meta, "targets": resume_targets, "root_path": root_path,
        }
        self.queued_rj_ids.add(rj_id)
        await self.download_queue.put(rj_id)
        self._emit_work_status(rj_id, "Queued")
        return {
            "status": "queued",
            "message": "Queued for download",
            "count": len(resume_targets),
            **summary,
        }

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

            if self.db.get_metadata_cache(rj_id, allow_stale=True):
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
    def _numeric_rj_id(rj_id: str) -> str:
        digits = rj_id.upper().removeprefix("RJ")
        if not digits.isdigit():
            raise ValueError(f"Invalid RJ id: {rj_id}")
        return str(int(digits))

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
        async def _fetch():
            logger.info(
                "METADATA_SLOT_ACQUIRE rj=%s limit=%s",
                rj_id, self.metadata_scheduler.concurrency,
            )
            meta_raw = await self.kernel.fetch(f"/api/workInfo/{rj_numeric}")
            if not meta_raw:
                detail = self.kernel.last_fetch_error or "empty response"
                raise RuntimeError(f"metadata request failed: {detail}")
            tracks_raw = await self.kernel.fetch(f"/api/tracks/{rj_numeric}?v=2")
            if not tracks_raw:
                detail = self.kernel.last_fetch_error or "empty response"
                raise RuntimeError(f"track request failed: {detail}")
            circle_name = meta_raw.get('circle', {}).get('name', 'Unknown')
            self.db.set_metadata_cache(
                rj_id=rj_id, title=meta_raw.get('title', ''),
                circle=circle_name,
                cover_url=meta_raw.get('mainCoverUrl', ''),
                metadata_raw=meta_raw, tracks_raw=tracks_raw)
            return meta_raw, tracks_raw

        return await self.metadata_scheduler.submit(f"prepare:{rj_id}", _fetch)

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
        rj_id = rj_id.strip().upper()
        if not rj_id.startswith("RJ"):
            rj_id = f"RJ{rj_id}"
        rj_numeric = self._numeric_rj_id(rj_id)

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
        stale_cached = None

        if not force_refresh:
            cached = self.db.get_metadata_cache(rj_id)
            stale_cached = self.db.get_metadata_cache(
                rj_id, allow_stale=True)
            if cached:
                try:
                    meta_raw = _json.loads(cached["metadata_json"])
                    tracks_raw = _json.loads(cached["tracks_json"])
                    from_cache = True
                    logging.info(f"Metadata cache HIT for {rj_id}")
                except Exception:
                    stale_cached = None
                    try:
                        self.db.invalidate_cache(rj_id)
                    except Exception:
                        pass

        if meta_raw is None:
            fetch_error = None
            try:
                meta_raw, tracks_raw = await self._fetch_metadata_live(
                    rj_id, rj_numeric)
            except Exception as e:
                fetch_error = e
                logger.error(f"Metadata fetch failed for {rj_id}: {e}")

            if (not meta_raw or tracks_raw is None) and stale_cached:
                try:
                    meta_raw = _json.loads(stale_cached["metadata_json"])
                    tracks_raw = _json.loads(stale_cached["tracks_json"])
                    from_cache = True
                    logger.warning(
                        f"Metadata cache STALE fallback for {rj_id}")
                except Exception:
                    meta_raw = None
                    tracks_raw = None

            if not meta_raw or tracks_raw is None:
                store = self.db.conn.execute(
                    "SELECT rj_id FROM works WHERE rj_id=?", (rj_id,)
                ).fetchone()
                if store:
                    self.db.execute_write(
                        "UPDATE works SET status='metadata_failed' WHERE rj_id=?",
                        (rj_id,))
                detail = str(fetch_error) if fetch_error else "empty response"
                self._emit_work_status(
                    rj_id,
                    f"Metadata failed ({detail}): proxy "
                    f"{self.config.metadata_proxy or self.config.proxy or 'off'}"
                )
                return None, None, None, False

        if tracks_raw is None:
            self._emit_work_status(rj_id, "Failed to fetch tracks")
            return None, None, None, False

        meta = self._build_metadata(rj_id, meta_raw)
        root_path = self.get_save_path(meta)

        # Create the destination before registering a prepared work.
        try:
            root_path.mkdir(parents=True, exist_ok=True)
            if not root_path.is_dir():
                raise NotADirectoryError(str(root_path))
        except OSError as e:
            logging.error(f"mkdir failed for {root_path}: {e}")
            self._emit_work_status(rj_id, f"Path failed: {e}")
            return None, None, None, False

        # Write works as 'prepared' only after the destination is usable.
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
    async def queue_job(self, rj_id: str, force_refresh: bool = False,
                        allow_duplicate: bool = False) -> dict:
        """Prepare and enqueue one work, honoring duplicate clicks and user stops."""
        rj_id = rj_id.strip().upper()
        if not rj_id.startswith("RJ"):
            rj_id = f"RJ{rj_id}"
        if rj_id in self.active_tasks:
            return {"status": "already_running", "rj_id": rj_id}
        if (rj_id in self.queued_rj_ids or rj_id in self.preparing_rj_ids
                or rj_id in self.resuming_rj_ids):
            return {"status": "already_queued", "rj_id": rj_id}

        self.preparing_rj_ids.add(rj_id)
        try:
            meta, targets, root_path, from_cache = await self.prepare_work(
                rj_id, force_refresh, allow_duplicate=allow_duplicate
            )
            if meta is None:
                return {"status": "prepare_failed", "rj_id": rj_id}
            if rj_id in self.user_cancelled_rjs:
                result = self.cancel_job(rj_id)
                return {**result, "rj_id": rj_id, "during_prepare": True}
            if rj_id in self.cancelled_rjs:
                result = self.pause_job(rj_id)
                return {**result, "rj_id": rj_id, "during_prepare": True}
            status_msg = "Queued (cached)" if from_cache else "Queued"
            self._emit_work_status(rj_id, status_msg)
            self._queued_work_data[rj_id] = {
                "meta": meta, "targets": targets, "root_path": root_path,
            }
            self.queued_rj_ids.add(rj_id)
            await self.download_queue.put(rj_id)
            return {
                "status": "queued", "rj_id": rj_id,
                "track_count": len(targets), "from_cache": from_cache,
                "allow_duplicate": allow_duplicate,
            }
        finally:
            self.preparing_rj_ids.discard(rj_id)

    # ══════════════════════════════════════════════
    #  download_file — returns bool
    # ══════════════════════════════════════════════
    async def download_file(self, track: TrackItem, meta: WorkMetadata,
                            cover_path: Optional[Path],
                            file_sem: asyncio.Semaphore,
                            refresher: Optional[SignedUrlRefresher] = None) -> bool:
        """Download one file with verified resume and real partial progress.

        ``refresher`` supplies signed-URL refresh (P0-C).  A 400/401/403 response
        is treated as an expired signed URL (never mechanically retried against
        the same URL): the file is retried once with a freshly-fetched URL for
        its RJ, and fails closed if the refresh yields no usable URL.
        """
        final_path = track.save_path
        part_path = final_path.with_suffix(final_path.suffix + ".part")

        if sys.platform == "win32" and len(str(final_path.absolute())) > 255:
            stem = self.sanitize(track.title)[:30]
            final_path = final_path.parent / f"{stem}{final_path.suffix}"
            part_path = final_path.with_suffix(final_path.suffix + ".part")
            track.save_path = final_path

        dl_id = self._make_dl_id(
            meta.rj_id, track.id or track.title, final_path, track.title)

        try:
            final_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logging.error(f"mkdir failed for {final_path}: {e}")
            self.stats.failed += 1
            self.db.upsert_download(
                dl_id, meta.rj_id, track.title, str(final_path),
                'failed', error=str(e))
            self._emit_progress(
                meta.rj_id, track.id or track.title, track.title,
                0, track.size, "failed")
            return False

        if final_path.exists() and final_path.stat().st_size == track.size > 0:
            self.stats.skipped += 1
            self.db.upsert_download(
                dl_id, meta.rj_id, track.title, str(final_path),
                'completed', track.size, track.size)
            self._emit_progress(
                meta.rj_id, track.id or track.title, track.title,
                track.size, track.size, "completed")
            if part_path.exists():
                try:
                    part_path.unlink()
                except OSError:
                    pass
            return True

        # Normalize all incomplete data into the .part file.  Appending a
        # ranged response to a new empty .part file would silently corrupt it.
        if final_path.exists() and final_path.stat().st_size != track.size:
            final_size = final_path.stat().st_size
            if final_size > 0 and (track.size <= 0 or final_size < track.size):
                if not part_path.exists() or part_path.stat().st_size < final_size:
                    os.replace(str(final_path), str(part_path))
                else:
                    final_path.unlink()
            else:
                final_path.unlink()

        if part_path.exists() and track.size > 0 and part_path.stat().st_size > track.size:
            part_path.unlink()

        retry_count = max(1, int(self.config.retry_count))
        existing_size = local_partial_size(final_path, part_path, track.size)

        for attempt in range(retry_count):
            self.db.upsert_download(
                dl_id, meta.rj_id, track.title, str(final_path),
                'downloading', existing_size, track.size)
            self._emit_progress(
                meta.rj_id, track.id or track.title, track.title,
                existing_size, track.size, "downloading")
            headers = {"Range": f"bytes={existing_size}-"} if existing_size else {}

            try:
                async with file_sem:
                    async with self._global_inflight_lock:
                        self._global_inflight += 1
                        global_inflight = self._global_inflight
                    self._per_rj_inflight[meta.rj_id] = \
                        self._per_rj_inflight.get(meta.rj_id, 0) + 1
                    work_inflight = self._per_rj_inflight[meta.rj_id]

                    try:
                        host = urllib.parse.urlparse(track.url).hostname or "unknown"
                        logger.info(
                            f"FILE_SLOT_ACQUIRE rj={meta.rj_id} "
                            f"track={track.title[:50]} host={host} size={track.size} "
                            f"resume={existing_size > 0} work_inflight={work_inflight} "
                            f"global_inflight={global_inflight}")
                        logger.info(
                            f"DOWNLOAD_ATTEMPT rj={meta.rj_id} "
                            f"track={track.title[:40]} attempt={attempt+1}/{retry_count} "
                            f"range={headers.get('Range', 'none')}")

                        success, resp_or_err = await self._stream_with_fallback(
                            track.url, headers)
                        if not success:
                            raise OSError(str(resp_or_err))

                        resp = resp_or_err
                        try:
                            local_size = local_partial_size(
                                final_path, part_path, track.size)
                            plan = plan_download_response(
                                status=resp.status,
                                headers=resp.headers,
                                requested_offset=existing_size,
                                expected_size=track.size,
                                local_size=local_size,
                            )
                            logger.info(
                                f"DOWNLOAD_RESP rj={meta.rj_id} "
                                f"track={track.title[:40]} http={resp.status} "
                                f"action={plan.action} "
                                f"content_range={resp.headers.get('Content-Range', 'none')}")

                            if plan.action == "complete_local":
                                if part_path.exists() and part_path.stat().st_size == track.size:
                                    os.replace(str(part_path), str(final_path))
                                if not final_path.exists() or final_path.stat().st_size != track.size:
                                    raise IOError("HTTP 416 completion verification failed")
                            elif plan.action == "retry_from_zero":
                                logging.warning(
                                    f"Reset partial download {track.title}: {plan.reason}")
                                if part_path.exists():
                                    part_path.unlink()
                                if final_path.exists() and final_path.stat().st_size != track.size:
                                    final_path.unlink()
                                existing_size = 0
                                if attempt == retry_count - 1:
                                    raise IOError(plan.reason)
                                if not resp.closed:
                                    resp.close()
                                await asyncio.sleep(
                                    self.config.retry_backoff ** attempt)
                                continue
                            elif plan.action == "http_error":
                                if (resp.status in {400, 401, 403}
                                        and refresher is not None):
                                    # Signed URL expired: never mechanically
                                    # retry the same URL (Issue #20).
                                    raise SignedUrlExpired(plan.reason)
                                raise IOError(plan.reason)
                            else:
                                downloaded = plan.initial_bytes
                                async with aiofiles.open(part_path, plan.mode) as f:
                                    async for chunk in resp.content.iter_chunked(
                                            self.config.chunk_size):
                                        await f.write(chunk)
                                        downloaded += len(chunk)
                                        self.stats.bytes_downloaded += len(chunk)
                                        self.speed.update(
                                            meta.rj_id, track.id or track.title,
                                            downloaded, len(chunk))
                                        self._emit_progress(
                                            meta.rj_id, track.id or track.title,
                                            track.title, downloaded, track.size,
                                            "downloading")

                                actual = part_path.stat().st_size
                                if track.size > 0 and actual != track.size:
                                    raise IOError(
                                        f"Size mismatch {actual} != {track.size}")
                                os.replace(str(part_path), str(final_path))
                        finally:
                            if not resp.closed:
                                resp.close()

                        if self.config.tag_audio and track.type == 'audio':
                            try:
                                AudioProcessor.apply_tags(
                                    final_path, meta, cover_path)
                            except Exception as e:
                                logging.warning(
                                    f"Tagging failed {final_path}: {e}")

                        final_size = final_path.stat().st_size
                        self.stats.success += 1
                        self.db.upsert_download(
                            dl_id, meta.rj_id, track.title, str(final_path),
                            'completed', final_size, track.size or final_size)
                        self._emit_progress(
                            meta.rj_id, track.id or track.title, track.title,
                            final_size, track.size or final_size, "completed")
                        return True
                    finally:
                        self._per_rj_inflight[meta.rj_id] = max(
                            0, self._per_rj_inflight.get(meta.rj_id, 1) - 1)
                        async with self._global_inflight_lock:
                            self._global_inflight = max(
                                0, self._global_inflight - 1)

            except asyncio.CancelledError:
                self.speed.pause_track(meta.rj_id, track.id or track.title)
                actual = local_partial_size(final_path, part_path, track.size)
                final_status = (
                    'cancelled' if meta.rj_id in self.user_cancelled_rjs else 'paused'
                )
                self.db.upsert_download(
                    dl_id, meta.rj_id, track.title, str(final_path),
                    final_status, actual, track.size)
                self._emit_progress(
                    meta.rj_id, track.id or track.title, track.title,
                    actual, track.size, final_status)
                raise
            except SignedUrlExpired as exc:
                # Refresh the track list once per RJ (single-flight) and retry
                # only this file against the fresh URL.  No retry_backoff, no
                # mechanical same-URL retry, and stored partial data (.part) is
                # preserved unless the fresh URL itself is unusable.
                fresh_url = await self._refresh_one_url(
                    meta.rj_id, track, refresher)
                if fresh_url is None:
                    actual = local_partial_size(final_path, part_path, track.size)
                    self.stats.failed += 1
                    final_status = 'paused' if actual > 0 else 'failed'
                    self.db.upsert_download(
                        dl_id, meta.rj_id, track.title, str(final_path),
                        final_status, actual, track.size,
                        error=f"Signed URL expired, refresh failed: {exc}")
                    self._emit_progress(
                        meta.rj_id, track.id or track.title, track.title,
                        actual, track.size, final_status)
                    logging.warning(
                        f"Download {track.title} {final_status} (signed URL closed "
                        f"after refresh, partial_bytes={actual}): {exc}")
                    return False
                track.url = fresh_url
                existing_size = local_partial_size(
                    final_path, part_path, track.size)
                if track.size > 0 and existing_size > track.size:
                    existing_size = track.size
                logging.info(
                    f"URL_REFRESH rj={meta.rj_id} track={track.title[:50]} "
                    f"fresh_url={fresh_url[:80]}")
                continue
            except Exception as e:
                actual = local_partial_size(final_path, part_path, track.size)
                last_attempt = attempt == retry_count - 1
                if last_attempt:
                    self.stats.failed += 1
                    final_status = 'paused' if actual > 0 else 'failed'
                    self.db.upsert_download(
                        dl_id, meta.rj_id, track.title, str(final_path),
                        final_status, actual, track.size, error=str(e))
                    self._emit_progress(
                        meta.rj_id, track.id or track.title, track.title,
                        actual, track.size, final_status)
                    logging.warning(
                        f"Download {track.title} {final_status} "
                        f"(partial_bytes={actual}): {e}")
                    return False
                existing_size = actual
                logging.warning(
                    f"Retry {attempt+1}/{retry_count} for {track.title}: {e}")
                await asyncio.sleep(self.config.retry_backoff ** attempt)

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
    async def _download_cover(self, rj_id: str, url: str,
                              root_path: Path) -> Optional[Path]:
        """Fetch a cover through the cover route and atomically publish its cache."""
        if not url:
            return None
        root_path.mkdir(parents=True, exist_ok=True)
        candidates = (
            root_path / "cover.jpg", root_path / "cover.jpeg",
            root_path / "cover.png", root_path / "cover.webp",
        )
        for candidate in candidates:
            try:
                if candidate.is_file() and candidate.stat().st_size > 0:
                    logger.info("COVER_CACHE_HIT rj=%s path=%s", rj_id, candidate)
                    return candidate
            except OSError:
                continue

        temp_path = root_path / ".cover.download.part"

        def extension_for(payload: bytes, content_type: str) -> str:
            lowered = (content_type or "").split(";", 1)[0].strip().lower()
            if payload.startswith(b"\x89PNG\r\n\x1a\n") or lowered == "image/png":
                return ".png"
            if (payload[:4] == b"RIFF" and payload[8:12] == b"WEBP") or lowered == "image/webp":
                return ".webp"
            if payload.startswith(b"\xff\xd8\xff") or lowered in {"image/jpeg", "image/jpg"}:
                return ".jpg"
            return ".jpg"

        async def attempt(*, direct: bool) -> Path:
            response = await self.kernel.stream(url, purpose="cover", direct=direct)
            try:
                if response.status < 200 or response.status >= 300:
                    raise OSError(f"cover HTTP {response.status}")
                payload = await response.read()
                if not payload:
                    raise OSError("empty cover response")
                final_path = root_path / f"cover{extension_for(payload, response.headers.get('Content-Type', ''))}"
                await asyncio.to_thread(temp_path.write_bytes, payload)
                os.replace(str(temp_path), str(final_path))
                for candidate in candidates:
                    if candidate != final_path:
                        try:
                            candidate.unlink(missing_ok=True)
                        except OSError:
                            pass
                logger.info(
                    "COVER_FETCH rj=%s route=%s bytes=%s path=%s",
                    rj_id, "direct" if direct else "cover", len(payload), final_path,
                )
                return final_path
            finally:
                if not response.closed:
                    response.close()

        try:
            return await asyncio.wait_for(attempt(direct=False), timeout=10.0)
        except asyncio.CancelledError:
            temp_path.unlink(missing_ok=True)
            raise
        except Exception as exc:
            logger.warning("Cover route failed for %s: %s", rj_id, exc)
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            if not getattr(self.config, "cover_fallback_to_direct", False):
                return None
        try:
            return await asyncio.wait_for(attempt(direct=True), timeout=10.0)
        except asyncio.CancelledError:
            temp_path.unlink(missing_ok=True)
            raise
        except Exception as exc:
            logger.warning("Explicit cover direct fallback failed for %s: %s", rj_id, exc)
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            return None

    # ── P0-C: fresh signed-URL refresh for expired media URLs ──
    async def _fetch_fresh_track_items(self, rj_id: str,
                                       root_path: Path) -> List[TrackItem]:
        """Fetch a live track list (with fresh signed URLs) for one RJ."""
        rj_numeric = self._numeric_rj_id(rj_id)
        _meta_raw, tracks_raw = await self._fetch_metadata_live(rj_id, rj_numeric)
        if not tracks_raw:
            raise RuntimeError("tracks refresh returned empty payload")
        hierarchy = self.parse_hierarchy(tracks_raw, root_path, root_path)

        def flatten(nodes):
            result = []
            for n in nodes:
                if n.type != 'folder':
                    result.append(n)
                result.extend(flatten(n.children))
            return result

        targets = self.deduplicate_tracks(flatten(hierarchy))
        if not targets:
            raise RuntimeError("tracks refresh returned no files")
        return targets

    async def _refresh_one_url(self, rj_id: str, track: TrackItem,
                               refresher: SignedUrlRefresher) -> Optional[str]:
        """Return a fresh download URL for one track (single-flight, 1/round)."""
        if refresher.refresh_count_for(rj_id) == 0:
            await refresher.refresh(rj_id)
        key = track.id or track.title
        return refresher.latest_url(rj_id, key)

    async def _process_download(self, rj_id: str, meta: WorkMetadata,
                                 targets: List[TrackItem],
                                 root_path: Path) -> None:
        cover_path = await self._download_cover(
            rj_id, meta.cover_url, root_path
        )

        self._emit_work_status(rj_id, "Downloading")

        # ── P0-B: bounded worker pool instead of one coroutine per file ──
        # A 686-file work must never create 686 live download coroutines.
        worker_count = max(1, int(self.config.file_concurrency))
        file_sem = asyncio.Semaphore(worker_count)
        refresher = SignedUrlRefresher(
            lambda rj: self._fetch_fresh_track_items(rj, root_path))
        self._per_rj_inflight[rj_id] = 0

        pool = DownloadWorkerPool(
            worker_count=worker_count,
            process=lambda t: self.download_file(
                t, meta, cover_path, file_sem, refresher),
            key_of=lambda t: id(t),
        )
        results = await pool.run(targets)

        # Clean up in-flight tracking
        self._per_rj_inflight.pop(rj_id, None)

        # Analyze results
        success_count = 0
        failed_count = 0
        cancelled_count = 0
        for t in targets:
            r = results.get(id(t))
            if r is True:
                success_count += 1
            elif isinstance(r, dict) and r.get("cancelled"):
                cancelled_count += 1
                failed_count += 1
            else:
                failed_count += 1

        total = len(targets)
        logging.info(f"Download results for {rj_id}: "
                     f"{success_count}/{total} success, {failed_count} failed")

        try:
            blocking_rows = [
                row for row in self.db.get_downloads_by_rj(rj_id)
                if str(row["status"] or "").lower() in {
                    "failed", "paused", "queued", "downloading",
                    "resuming", "cancelled", "metadata_failed",
                }
            ]
            if failed_count == 0 and cancelled_count == 0 and not blocking_rows:
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
                # Distinguish a durable user cancellation from a pause.
                if (rj_id in self.user_cancelled_rjs or
                        (self.db.get_works_status(rj_id) or "").lower() == "cancelled"):
                    self._emit_work_status(rj_id, "Cancelled")
                else:
                    self._emit_work_status(rj_id, "Paused (partial)")
            else:
                # Some failed — register as partial, do NOT overwrite failed
                self._emit_work_status(
                    rj_id, f"Partially completed ({success_count}/{total})")
                success_targets = [
                    t for t in targets if results.get(id(t)) is True]
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