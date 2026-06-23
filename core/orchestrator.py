import asyncio
import json as _json
import os
import re
import sys
import logging
import urllib.parse
from pathlib import Path
from typing import List, Callable, Optional, Dict

import aiofiles
import yarl

from core.models import WorkMetadata, TrackItem, SessionStats
from core.config import ConfigManager
from core.database import LibraryVault
from core.network import NetworkKernel
from core.audio import AudioProcessor

CHUNK_SIZE = 10485760  # 10MB chunks


class Orchestrator:
    """Orchestrates download operations with metadata cache and download state."""

    def __init__(self, kernel: NetworkKernel, config: ConfigManager,
                 db: LibraryVault):
        self.kernel = kernel
        self.config = config
        self.db = db
        self.stats = SessionStats()
        self.sem = asyncio.Semaphore(config.max_concurrent)
        self.download_queue: asyncio.Queue = asyncio.Queue()
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self.cancelled_rjs: set = set()
        self.on_progress: Optional[Callable] = None
        self.on_work_status: Optional[Callable] = None

    # ── callbacks ──
    def set_callbacks(self, on_progress, on_work_status):
        self.on_progress = on_progress
        self.on_work_status = on_work_status

    def _emit_progress(self, rj_id, track_title, downloaded, total, status):
        if self.on_progress:
            try:
                self.on_progress(rj_id, track_title, downloaded, total, status)
            except Exception:
                pass

    def _emit_work_status(self, rj_id, status):
        if self.on_work_status:
            try:
                self.on_work_status(rj_id, status)
            except Exception:
                pass

    # ── worker loop ──
    async def boot_worker(self):
        while True:
            rj_id, job_coro = await self.download_queue.get()
            if rj_id in self.cancelled_rjs:
                self.cancelled_rjs.discard(rj_id)
                self.download_queue.task_done()
                continue
            task = asyncio.create_task(job_coro)
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

    def pause_job(self, rj_id):
        if rj_id in self.active_tasks:
            self.active_tasks[rj_id].cancel()
        else:
            self.cancelled_rjs.add(rj_id)
            self._emit_work_status(rj_id, "Paused")

    def cancel_job(self, rj_id):
        self.pause_job(rj_id)

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

    # ══════════════════════════════════════════════
    #  P1-1: Metadata cache integration
    # ══════════════════════════════════════════════
    async def _fetch_metadata_live(self, rj_id: str, rj_numeric: str):
        """Fetch fresh metadata + tracks from API, cache in DB."""
        meta_raw = await self.kernel.fetch(f"/api/workInfo/{rj_numeric}")
        if not meta_raw:
            return None, None

        tracks_raw = await self.kernel.fetch(f"/api/tracks/{rj_numeric}?v=2")
        if not tracks_raw:
            return meta_raw, None

        # Persist to cache
        circle_name = meta_raw.get('circle', {}).get('name', 'Unknown')
        self.db.set_metadata_cache(
            rj_id=rj_id,
            title=meta_raw.get('title', ''),
            circle=circle_name,
            cover_url=meta_raw.get('mainCoverUrl', ''),
            metadata_raw=meta_raw,
            tracks_raw=tracks_raw,
        )
        return meta_raw, tracks_raw

    # ══════════════════════════════════════════════
    #  queue_job — cache-aware
    # ══════════════════════════════════════════════
    async def queue_job(self, rj_id: str, force_refresh: bool = False) -> None:
        self._emit_work_status(rj_id, "Fetching metadata...")

        # Normalize
        if not rj_id.upper().startswith("RJ"):
            rj_id = f"RJ{rj_id}"
        rj_numeric = rj_id[2:]

        # ── Check metadata cache ──
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
                    self.db.invalidate_cache(rj_id)

        # ── Fetch if not cached ──
        if meta_raw is None:
            meta_raw, tracks_raw = await self._fetch_metadata_live(
                rj_id, rj_numeric)
            if not meta_raw:
                self._emit_work_status(rj_id, "Failed to fetch metadata")
                return

        if tracks_raw is None:
            self._emit_work_status(rj_id, "Failed to fetch tracks")
            return

        # ── Build WorkMetadata ──
        meta = WorkMetadata(
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

        # ── Parse hierarchy ──
        root_path = self.get_save_path(meta)
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
            return

        # ── Initialize download state in DB ──
        for t in targets:
            dl_id = f"{rj_id}:{t.id or t.title}"
            existing_size = t.save_path.stat().st_size if t.save_path.exists() else 0
            self.db.upsert_download(
                dl_id, rj_id, t.title, str(t.save_path),
                status='completed' if existing_size == t.size > 0 else 'queued',
                downloaded_bytes=existing_size, total_bytes=t.size
            )
            self._emit_progress(rj_id, t.title, existing_size, t.size, "pending")

        status_msg = "Queued (cached)" if from_cache else "Queued"
        self._emit_work_status(rj_id, status_msg)

        await self.download_queue.put(
            (rj_id, self._process_download(rj_id, meta, targets, root_path))
        )

    # ══════════════════════════════════════════════
    #  download_file — with state updates
    # ══════════════════════════════════════════════
    async def download_file(self, track: TrackItem, meta: WorkMetadata,
                            cover_path: Optional[Path]) -> None:
        final_path = track.save_path
        part_path = final_path.with_suffix(final_path.suffix + ".part")
        dl_id = f"{meta.rj_id}:{track.id or track.title}"

        # Windows long path
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
            self._emit_progress(meta.rj_id, track.title, 0, track.size, "failed")
            return

        # Already complete
        if final_path.exists() and final_path.stat().st_size == track.size:
            self.stats.skipped += 1
            self.db.upsert_download(dl_id, meta.rj_id, track.title,
                                    str(final_path), 'completed',
                                    track.size, track.size)
            self._emit_progress(meta.rj_id, track.title, track.size, track.size, "completed")
            if part_path.exists():
                try: part_path.unlink()
                except OSError: pass
            return

        # Existing partial
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

        # ── download loop ──
        for attempt in range(3):
            self.db.upsert_download(dl_id, meta.rj_id, track.title,
                                    str(final_path), 'downloading',
                                    existing_size, track.size)
            self._emit_progress(meta.rj_id, track.title, existing_size, track.size, "downloading")
            try:
                headers = {}
                if existing_size > 0:
                    headers["Range"] = f"bytes={existing_size}-"

                async with self.sem:
                    async with await self.kernel.stream(
                        track.url, headers, purpose='download'
                    ) as resp:
                        if resp.status == 416:
                            self.stats.skipped += 1
                            self.db.upsert_download(
                                dl_id, meta.rj_id, track.title,
                                str(final_path), 'completed', track.size, track.size)
                            self._emit_progress(meta.rj_id, track.title,
                                                track.size, track.size, "completed")
                            return
                        if resp.status not in (200, 206):
                            if attempt == 2:
                                self.stats.failed += 1
                                self.db.upsert_download(
                                    dl_id, meta.rj_id, track.title,
                                    str(final_path), 'failed',
                                    error=f"HTTP {resp.status}")
                                self._emit_progress(meta.rj_id, track.title,
                                                    existing_size, track.size, "failed")
                            await asyncio.sleep(1 * (attempt + 1))
                            continue

                        is_partial = resp.status == 206
                        if is_partial:
                            cr = resp.headers.get("Content-Range", "")
                            m = re.match(r"bytes\s+(\d+)-\d+/(\d+)", cr)
                            if m and int(m.group(1)) != existing_size:
                                logging.warning(f"Range mismatch for {track.title}, restarting")
                                existing_size = 0
                                is_partial = False

                        mode = "ab" if is_partial else "wb"
                        target = part_path
                        if resp.status == 200:
                            existing_size = 0
                            mode = "wb"
                        downloaded = existing_size if is_partial else 0

                        async with aiofiles.open(target, mode) as f:
                            async for chunk in resp.content.iter_chunked(CHUNK_SIZE):
                                await f.write(chunk)
                                downloaded += len(chunk)
                                self.stats.bytes_downloaded += len(chunk)
                                self._emit_progress(meta.rj_id, track.title,
                                                    downloaded, track.size, "downloading")

                # Validate
                actual = target.stat().st_size
                if actual != track.size:
                    logging.warning(f"Size mismatch {track.title}: {actual} vs {track.size}")

                # Atomic rename
                if target == part_path:
                    os.replace(str(part_path), str(final_path))

                # Tags
                if self.config.tag_audio and track.type == 'audio':
                    try:
                        AudioProcessor.apply_tags(final_path, meta, cover_path)
                    except Exception as e:
                        logging.warning(f"Tagging failed {final_path}: {e}")

                self.stats.success += 1
                self.db.upsert_download(dl_id, meta.rj_id, track.title,
                                        str(final_path), 'completed',
                                        track.size, track.size)
                self._emit_progress(meta.rj_id, track.title, track.size, track.size, "completed")
                return

            except asyncio.CancelledError:
                self.db.upsert_download(dl_id, meta.rj_id, track.title,
                                        str(final_path), 'paused',
                                        existing_size, track.size)
                raise
            except Exception as e:
                if attempt == 2:
                    self.stats.failed += 1
                    self.db.upsert_download(dl_id, meta.rj_id, track.title,
                                            str(final_path), 'failed', error=str(e))
                    self._emit_progress(meta.rj_id, track.title, 0, track.size, "failed")
                    logging.error(f"Error downloading {track.title}: {e}", exc_info=True)
                else:
                    logging.warning(f"Retry {attempt+1}/3 for {track.title}: {e}")
                await asyncio.sleep(1 * (attempt + 1))

    # ══════════════════════════════════════════════
    #  _process_download — cover uses cover proxy
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
                logging.warning(f"Cover download timed out for {rj_id}")
                cover_path = None
            except Exception as e:
                logging.error(f"Cover download failed for {rj_id}: {e}")
                cover_path = None
        else:
            cover_path = None

        self._emit_work_status(rj_id, "Downloading")

        coros = [self.download_file(t, meta, cover_path) for t in targets]
        await asyncio.gather(*coros)

        # Register in works library
        try:
            final_size = sum(
                t.save_path.stat().st_size
                for t in targets if t.save_path.exists()
            )
            self.db.register(meta, final_size, root_path)
            # Mark all as registered and clean up terminal states
            for t in targets:
                dl_id = f"{meta.rj_id}:{t.id or t.title}"
                self.db.upsert_download(dl_id, meta.rj_id, t.title,
                                        str(t.save_path), 'registered',
                                        t.size, t.size)
        except Exception as e:
            logging.error(f"Failed to register work {rj_id}: {e}")

        self._emit_work_status(rj_id, "Completed")
