import asyncio
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
    """Orchestrates download operations and file management."""

    def __init__(self, kernel: NetworkKernel, config: ConfigManager, db: LibraryVault):
        self.kernel = kernel
        self.config = config
        self.db = db
        self.stats = SessionStats()
        self.sem = asyncio.Semaphore(config.max_concurrent)
        self.download_queue: asyncio.Queue = asyncio.Queue()
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self.cancelled_rjs: set = set()
        # on_progress(rj_id, track_id, downloaded, total, status_text)
        self.on_progress: Optional[Callable[[str, str, int, int, str], None]] = None
        # on_work_status(rj_id, status_text)
        self.on_work_status: Optional[Callable[[str, str], None]] = None

    def set_callbacks(self, on_progress: Callable, on_work_status: Callable):
        self.on_progress = on_progress
        self.on_work_status = on_work_status

    def _emit_progress(self, rj_id: str, track_title: str, downloaded: int, total: int, status: str):
        if self.on_progress:
            try:
                self.on_progress(rj_id, track_title, downloaded, total, status)
            except Exception:
                pass

    def _emit_work_status(self, rj_id: str, status: str):
        if self.on_work_status:
            try:
                self.on_work_status(rj_id, status)
            except Exception:
                pass

    async def boot_worker(self):
        """Background worker to process queued jobs sequentially."""
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
                logging.info(f"Task {rj_id} was paused/cancelled.")
                self._emit_work_status(rj_id, "Paused")
            except Exception as e:
                logging.error(f"Job failed for {rj_id}: {e}", exc_info=True)
                self._emit_work_status(rj_id, f"Error: {e}")
            finally:
                self.active_tasks.pop(rj_id, None)
                self.download_queue.task_done()

    def pause_job(self, rj_id: str):
        """Pause a job by cancelling its task or marking it to be skipped."""
        if rj_id in self.active_tasks:
            self.active_tasks[rj_id].cancel()
        else:
            self.cancelled_rjs.add(rj_id)
            self._emit_work_status(rj_id, "Paused")

    def cancel_job(self, rj_id: str):
        """Cancel a job completely."""
        self.pause_job(rj_id)

    @staticmethod
    def sanitize(name: str) -> str:
        """Sanitize filename by removing invalid characters."""
        # Remove leading/trailing dots and spaces (Windows restriction)
        name = name.strip(". ")
        # Replace invalid filesystem characters
        name = re.sub(r'[<>:"/\\|?*]', '_', name)
        # Remove control characters
        name = re.sub(r'[\x00-\x1f]', '', name)
        # Collapse multiple underscores
        name = re.sub(r'_+', '_', name)
        # Normalize whitespace
        name = ' '.join(name.split())
        return name[:200] if name else "Unknown"

    @staticmethod
    def deduplicate_tracks(targets: List[TrackItem]) -> List[TrackItem]:
        """Ensure no two tracks have the same save_path by appending suffixes."""
        seen: Dict[str, int] = {}
        for t in targets:
            key = str(t.save_path)
            if key in seen:
                seen[key] += 1
                stem = t.save_path.stem
                suffix = t.save_path.suffix
                new_name = f"{stem}_{seen[key]}{suffix}"
                t.save_path = t.save_path.parent / new_name
                t.title = f"{t.title}_{seen[key]}"
            else:
                seen[key] = 1
        return targets

    def get_save_path(self, meta: WorkMetadata) -> Path:
        """Generate save path for a work based on template."""
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

    def categorize_path(self, root: Path, filename: str, ftype: str) -> Path:
        """Categorize file into appropriate subdirectory."""
        if not self.config.sort_files:
            return root / filename

        ext = Path(filename).suffix.lower()

        if ftype == 'audio' or ext in ['.mp3', '.wav', '.flac', '.m4a', '.ogg', '.aac', '.wma']:
            return root / "Audio" / filename
        elif ftype == 'image' or ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp']:
            return root / "Images" / filename
        elif ftype == 'text' or ext in ['.txt', '.pdf', '.doc', '.docx', '.html']:
            return root / "Text" / filename
        else:
            return root / "Other" / filename

    def parse_hierarchy(self, data: List[dict], root_path: Path,
                        base_path: Path, level: int = 0) -> List[TrackItem]:
        """Parse hierarchical track data into TrackItem objects."""
        items = []

        for node in data:
            title = self.sanitize(node.get("title", "Unknown"))

            if node.get("type") == "folder":
                folder_item = TrackItem(
                    id="dir",
                    title=title,
                    type="folder",
                    url="",
                    size=0,
                    save_path=root_path / title,
                    level=level
                )
                children = node.get("children", [])
                folder_item.children = self.parse_hierarchy(
                    children,
                    root_path / title,
                    base_path,
                    level + 1
                )
                items.append(folder_item)

            elif "mediaDownloadUrl" in node:
                if self.config.sort_files:
                    save_path = self.categorize_path(base_path, title, node.get("type", "file"))
                else:
                    save_path = root_path / title

                raw_url = node["mediaDownloadUrl"]
                parsed_url = urllib.parse.urlsplit(raw_url)
                safe_path = urllib.parse.quote(urllib.parse.unquote(parsed_url.path))
                fixed_url = urllib.parse.urlunsplit(
                    (parsed_url.scheme, parsed_url.netloc, safe_path,
                     parsed_url.query, parsed_url.fragment)
                )

                track = TrackItem(
                    id=str(node.get("id", "")),
                    title=title,
                    type=node.get("type", "file"),
                    url=str(yarl.URL(fixed_url, encoded=True)),
                    size=node.get("size", 0),
                    save_path=save_path,
                    level=level
                )
                items.append(track)

        return items

    async def download_file(self, track: TrackItem, meta: WorkMetadata,
                            cover_path: Optional[Path]) -> None:
        """Download a single file with Range-based resume and .part temp files."""
        final_path = track.save_path
        part_path = final_path.with_suffix(final_path.suffix + ".part")

        # --- Windows long path handling ---
        if sys.platform == "win32" and len(str(final_path.absolute())) > 255:
            stem = self.sanitize(track.title)[:30]
            final_path = final_path.parent / f"{stem}{final_path.suffix}"
            part_path = final_path.with_suffix(final_path.suffix + ".part")
            track.save_path = final_path  # update for later statistics

        # Ensure parent directory exists
        try:
            final_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logging.error(f"Failed to create directory for {final_path}: {e}")
            self.stats.failed += 1
            self._emit_progress(meta.rj_id, track.title, 0, track.size, "failed")
            return

        # Check if final file already exists and is complete
        if final_path.exists() and final_path.stat().st_size == track.size:
            self.stats.skipped += 1
            self._emit_progress(meta.rj_id, track.title, track.size, track.size, "completed")
            # Clean up orphaned .part if present
            if part_path.exists():
                try:
                    part_path.unlink()
                except OSError:
                    pass
            return

        # Determine existing partial download
        existing_size = 0
        if part_path.exists():
            existing_size = part_path.stat().st_size
            # Discard if larger than expected (corrupted)
            if existing_size > track.size:
                logging.warning(f"Part file larger than expected for {track.title}, resetting")
                existing_size = 0
                try:
                    part_path.unlink()
                except OSError:
                    pass
        elif final_path.exists():
            # Final file exists but size doesn't match — resume from it
            existing_size = final_path.stat().st_size
            if existing_size > track.size:
                existing_size = 0

        # --- Attempt download with retries ---
        for attempt in range(3):
            try:
                headers = {}
                if existing_size > 0:
                    headers["Range"] = f"bytes={existing_size}-"

                self._emit_progress(meta.rj_id, track.title, existing_size, track.size, "downloading")

                async with self.sem:
                    async with await self.kernel.stream(track.url, headers) as resp:
                        # --- Range response validation ---
                        if resp.status == 416:  # Range Not Satisfiable
                            # File already fully downloaded but server disagrees on size
                            self.stats.skipped += 1
                            self._emit_progress(meta.rj_id, track.title, track.size, track.size, "completed")
                            return

                        if resp.status not in (200, 206):
                            if attempt == 2:
                                self.stats.failed += 1
                                self._emit_progress(meta.rj_id, track.title, existing_size, track.size, "failed")
                                logging.error(f"Failed: {track.title} (HTTP {resp.status})")
                            await asyncio.sleep(1 * (attempt + 1))
                            continue

                        # If server sent 206, validate Content-Range
                        is_partial = resp.status == 206
                        if is_partial:
                            content_range = resp.headers.get("Content-Range", "")
                            if content_range:
                                # Example: "bytes 1024-2047/2048"
                                match = re.match(r"bytes\s+(\d+)-\d+/(\d+)", content_range)
                                if match:
                                    range_start = int(match.group(1))
                                    if range_start != existing_size:
                                        logging.warning(
                                            f"Content-Range start ({range_start}) != existing ({existing_size}), "
                                            f"restarting from 0 for {track.title}"
                                        )
                                        existing_size = 0
                                        is_partial = False

                        # Write mode
                        mode = "ab" if is_partial else "wb"
                        target = part_path if not is_partial else part_path
                        # If we got 200 (no Range support), start fresh
                        if resp.status == 200:
                            existing_size = 0
                            mode = "wb"
                            target = part_path

                        downloaded = existing_size if is_partial else 0
                        async with aiofiles.open(target, mode) as f:
                            async for chunk in resp.content.iter_chunked(CHUNK_SIZE):
                                await f.write(chunk)
                                downloaded += len(chunk)
                                self.stats.bytes_downloaded += len(chunk)
                                self._emit_progress(
                                    meta.rj_id, track.title, downloaded, track.size, "downloading"
                                )

                # --- Post-download validation ---
                actual_size = target.stat().st_size
                if actual_size != track.size:
                    logging.warning(
                        f"Size mismatch for {track.title}: expected {track.size}, got {actual_size}"
                    )
                    # Don't fail immediately — some servers may report slightly different sizes

                # --- Atomically rename .part to final ---
                if target == part_path:
                    try:
                        os.replace(str(part_path), str(final_path))
                    except OSError as e:
                        logging.error(f"Failed to rename part file for {track.title}: {e}")
                        self.stats.failed += 1
                        self._emit_progress(meta.rj_id, track.title, 0, track.size, "failed")
                        return

                # --- Apply audio tags ---
                if self.config.tag_audio and track.type == 'audio':
                    try:
                        AudioProcessor.apply_tags(final_path, meta, cover_path)
                    except Exception as e:
                        logging.warning(f"Tagging failed for {final_path}: {e}")

                self.stats.success += 1
                self._emit_progress(meta.rj_id, track.title, track.size, track.size, "completed")
                return

            except asyncio.CancelledError:
                # Don't retry on cancellation; clean up and re-raise
                raise
            except Exception as e:
                if attempt == 2:
                    self.stats.failed += 1
                    self._emit_progress(meta.rj_id, track.title, 0, track.size, "failed")
                    logging.error(f"Error downloading {track.title}: {e}", exc_info=True)
                else:
                    logging.warning(f"Retry {attempt + 1}/3 for {track.title}: {e}")
                await asyncio.sleep(1 * (attempt + 1))

    async def queue_job(self, rj_id: str) -> None:
        """Queue a download job for a specific RJ code, pre-fetching metadata."""
        self._emit_work_status(rj_id, "Fetching metadata...")

        # Ensure rj_id has the RJ prefix and extract numeric part for API
        if not rj_id.upper().startswith("RJ"):
            rj_id = f"RJ{rj_id}"
        rj_numeric = rj_id[2:]  # strip "RJ" prefix

        # --- Fetch metadata ---
        meta_raw = await self.kernel.fetch(f"/api/workInfo/{rj_numeric}")
        if not meta_raw:
            self._emit_work_status(rj_id, "Failed to fetch metadata")
            logging.error(f"Failed to fetch metadata for {rj_id}")
            return

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

        self._emit_work_status(rj_id, "Fetching track list...")

        # --- Fetch tracks ---
        tracks_raw = await self.kernel.fetch(f"/api/tracks/{rj_numeric}?v=2")
        if not tracks_raw:
            self._emit_work_status(rj_id, "Failed to fetch tracks")
            logging.error(f"Failed to fetch tracks for {rj_id}")
            return

        root_path = self.get_save_path(meta)
        hierarchy = self.parse_hierarchy(tracks_raw, root_path, root_path)

        # --- Flatten and deduplicate ---
        def flatten(nodes: List[TrackItem]) -> List[TrackItem]:
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

        # --- Emit initial track states for UI ---
        for t in targets:
            existing_size = t.save_path.stat().st_size if t.save_path.exists() else 0
            self._emit_progress(meta.rj_id, t.title, existing_size, t.size, "pending")

        self._emit_work_status(rj_id, "Queued")

        await self.download_queue.put((rj_id, self._process_download(rj_id, meta, targets, root_path)))

    async def _process_download(self, rj_id: str, meta: WorkMetadata,
                                 targets: List[TrackItem], root_path: Path) -> None:
        """Actually process the download from the queue."""

        # --- Download cover image ---
        cover_path: Optional[Path] = root_path / "cover.jpg"
        if meta.cover_url:
            root_path.mkdir(parents=True, exist_ok=True)
            try:
                async def fetch_cover():
                    async with await self.kernel.stream(meta.cover_url) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            cover_path.write_bytes(data)

                await asyncio.wait_for(fetch_cover(), timeout=10.0)
            except asyncio.TimeoutError:
                logging.warning(f"Cover download timed out for {rj_id}")
                cover_path = None
            except Exception as e:
                logging.error(f"Failed to fetch cover for {rj_id}: {e}")
                cover_path = None
        else:
            cover_path = None

        self._emit_work_status(rj_id, "Downloading")

        # --- Download all tracks concurrently ---
        coros = [self.download_file(t, meta, cover_path) for t in targets]
        await asyncio.gather(*coros)

        # --- Calculate final size and register ---
        try:
            final_size = sum(
                t.save_path.stat().st_size
                for t in targets
                if t.save_path.exists()
            )
            self.db.register(meta, final_size, root_path)
        except Exception as e:
            logging.error(f"Failed to register work {rj_id} in database: {e}")

        self._emit_work_status(rj_id, "Completed")
