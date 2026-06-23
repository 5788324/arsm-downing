import asyncio
import os
import re
import logging
import urllib.parse
from pathlib import Path
from typing import List, Callable, Optional
import aiofiles

from core.models import WorkMetadata, TrackItem, SessionStats
from core.config import ConfigManager
from core.database import LibraryVault
from core.network import NetworkKernel
from core.audio import AudioProcessor

CHUNK_SIZE = 10485760  # 10MB chunks for better UI responsiveness

class Orchestrator:
    """Orchestrates download operations and file management."""
    def __init__(self, kernel: NetworkKernel, config: ConfigManager, db: LibraryVault):
        self.kernel = kernel
        self.config = config
        self.db = db
        self.stats = SessionStats()
        self.sem = None
        self.download_queue = asyncio.Queue()
        self.active_tasks = {}
        self.cancelled_rjs = set()
        # on_progress(rj_id, track_id, downloaded, total, status_text)
        self.on_progress: Optional[Callable[[str, str, int, int, str], None]] = None
        # on_work_status(rj_id, status_text)
        self.on_work_status: Optional[Callable[[str, str], None]] = None

    def set_callbacks(self, on_progress: Callable, on_work_status: Callable):
        self.on_progress = on_progress
        self.on_work_status = on_work_status

    async def boot_worker(self):
        """Background worker to process queued jobs sequentially."""
        while True:
            rj_id, job_coro = await self.download_queue.get()
            
            if rj_id in self.cancelled_rjs:
                self.cancelled_rjs.remove(rj_id)
                self.download_queue.task_done()
                continue
                
            task = asyncio.create_task(job_coro)
            self.active_tasks[rj_id] = task
            try:
                await task
            except asyncio.CancelledError:
                logging.info(f"Task {rj_id} was paused/cancelled.")
                if self.on_work_status:
                    self.on_work_status(rj_id, "Paused")
            except Exception as e:
                logging.error(f"Job failed: {e}")
            finally:
                self.active_tasks.pop(rj_id, None)
                self.download_queue.task_done()

    def pause_job(self, rj_id: str):
        """Pause a job by cancelling its task or marking it to be skipped."""
        if rj_id in self.active_tasks:
            self.active_tasks[rj_id].cancel()
        else:
            self.cancelled_rjs.add(rj_id)
            if self.on_work_status:
                self.on_work_status(rj_id, "Paused")

    def cancel_job(self, rj_id: str):
        """Cancel a job completely."""
        self.pause_job(rj_id)

    @staticmethod
    def sanitize(name: str) -> str:
        """Sanitize filename by removing invalid characters."""
        name = re.sub(r'[<>:"/\\|?*]', '_', name)
        name = re.sub(r'[\x00-\x1f]', '', name)
        return name.strip()[:200]

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
            folder = f"RJ{meta.rj_id} {self.sanitize(meta.title)}"
        
        return self.config.output_dir / folder

    def categorize_path(self, root: Path, filename: str, ftype: str) -> Path:
        """Categorize file into appropriate subdirectory."""
        if not self.config.sort_files:
            return root / filename
            
        ext = Path(filename).suffix.lower()
        
        if ftype == 'audio' or ext in ['.mp3', '.wav', '.flac', '.m4a', '.ogg']:
            return root / "Audio" / filename
        elif ftype == 'image' or ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']:
            return root / "Images" / filename
        elif ftype == 'text' or ext in ['.txt', '.pdf', '.doc', '.docx']:
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
                
                import yarl
                raw_url = node["mediaDownloadUrl"]
                parsed_url = urllib.parse.urlsplit(raw_url)
                safe_path = urllib.parse.quote(urllib.parse.unquote(parsed_url.path))
                fixed_url = urllib.parse.urlunsplit((parsed_url.scheme, parsed_url.netloc, safe_path, parsed_url.query, parsed_url.fragment))
                
                track = TrackItem(
                    id=node.get("id", ""),
                    title=title,
                    type=node.get("type", "file"),
                    url=str(yarl.URL(fixed_url, encoded=True)),
                    size=node.get("size", 0),
                    save_path=save_path,
                    level=level
                )
                items.append(track)
                
        return items

    async def download_file(self, track: TrackItem, meta: WorkMetadata, cover: Path) -> None:
        """Download a single file with individual progress tracking."""
        path = track.save_path
        import sys

        if sys.platform == "win32" and len(str(path.absolute())) > 255:
            stem = track.title[:30]
            path = path.parent / f"{stem}{path.suffix}"

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logging.error(f"Failed to create directory: {e}")
            self.stats.failed += 1
            if self.on_progress:
                self.on_progress(meta.rj_id, track.title, 0, track.size, "failed")
            return

        for attempt in range(3):
            try:
                existing_size = path.stat().st_size if path.exists() else 0
                
                if existing_size == track.size:
                    if attempt == 0:
                        self.stats.skipped += 1
                    if self.on_progress:
                        self.on_progress(meta.rj_id, track.title, track.size, track.size, "completed")
                    return
                    
                if existing_size > track.size:
                    existing_size = 0

                headers = {"Range": f"bytes={existing_size}-"} if existing_size else {}
                
                if self.on_progress:
                    self.on_progress(meta.rj_id, track.title, existing_size, track.size, "downloading")

                if self.sem is None:
                    self.sem = asyncio.Semaphore(self.config.max_concurrent)

                async with self.sem:
                    async with await self.kernel.stream(track.url, headers) as resp:
                        if resp.status == 416:
                            self.stats.skipped += 1
                            if self.on_progress:
                                self.on_progress(meta.rj_id, track.title, track.size, track.size, "completed")
                            return
                            
                        if resp.status not in [200, 206]:
                            if attempt == 2:
                                self.stats.failed += 1
                                if self.on_progress:
                                    self.on_progress(meta.rj_id, track.title, existing_size, track.size, "failed")
                                logging.error(f"Failed: {track.title} (HTTP {resp.status})")
                            continue
                        
                        mode = "ab" if resp.status == 206 else "wb"
                        downloaded = existing_size
                        async with aiofiles.open(path, mode) as f:
                            async for chunk in resp.content.iter_chunked(CHUNK_SIZE):
                                await f.write(chunk)
                                downloaded += len(chunk)
                                self.stats.bytes_downloaded += len(chunk)
                                if self.on_progress:
                                    self.on_progress(meta.rj_id, track.title, downloaded, track.size, "downloading")
                
                if self.config.tag_audio and track.type == 'audio':
                    AudioProcessor.apply_tags(path, meta, cover)
                
                self.stats.success += 1
                if self.on_progress:
                    self.on_progress(meta.rj_id, track.title, track.size, track.size, "completed")
                return
                
            except Exception as e:
                if attempt == 2:
                    self.stats.failed += 1
                    if self.on_progress:
                        self.on_progress(meta.rj_id, track.title, 0, track.size, "failed")
                    logging.error(f"Error downloading {track.title}: {e}")
                await asyncio.sleep(1)

    async def queue_job(self, rj_id: str) -> None:
        """Queue a download job for a specific RJ code, pre-fetching metadata."""
        if self.on_work_status:
            self.on_work_status(rj_id, "Fetching metadata...")
            
        rj_numeric = rj_id.upper().replace("RJ", "")
        meta_raw = await self.kernel.fetch(f"/api/workInfo/{rj_numeric}")
        if not meta_raw:
            if self.on_work_status:
                self.on_work_status(rj_id, "Failed to fetch metadata")
            return
        
        meta = WorkMetadata(
            rj_id=rj_id,
            title=meta_raw.get('title', 'Unknown'),
            circle=meta_raw.get('circle', {}).get('name', 'Unknown'),
            cv=[v['name'] for v in meta_raw.get('vas', [])],
            tags=[t['name'] for t in meta_raw.get('tags', [])],
            price=meta_raw.get('price', 0),
            source_url=meta_raw.get('source_url', ''),
            dl_count=meta_raw.get('dl_count', 0),
            rating=meta_raw.get('rate_average_2dp', 0.0),
            release_date=meta_raw.get('release_date', ''),
            cover_url=meta_raw.get('mainCoverUrl', '')
        )
        
        if self.on_work_status:
            self.on_work_status(rj_id, "Fetching track list...")

        tracks_raw = await self.kernel.fetch(f"/api/tracks/{rj_numeric}?v=2")
        if not tracks_raw:
            if self.on_work_status:
                self.on_work_status(rj_id, "Failed to fetch tracks")
            return
        
        root_path = self.get_save_path(meta)
        hierarchy = self.parse_hierarchy(tracks_raw, root_path, root_path)
        
        def flatten(nodes: List[TrackItem]) -> List[TrackItem]:
            result = []
            for n in nodes:
                if n.type != 'folder':
                    result.append(n)
                result.extend(flatten(n.children))
            return result
            
        targets = flatten(hierarchy)
        
        if not targets:
            if self.on_work_status:
                self.on_work_status(rj_id, "No tracks found")
            return
            
        # Initialize DB tracking for all tracks to create placeholder UI
        for t in targets:
            existing_size = t.save_path.stat().st_size if t.save_path.exists() else 0
            if self.on_progress:
                self.on_progress(meta.rj_id, t.title, existing_size, t.size, "pending")
            
        if self.on_work_status:
            self.on_work_status(rj_id, "Queued")
            
        await self.download_queue.put((rj_id, self._process_download(rj_id, meta, targets, root_path)))

    async def _process_download(self, rj_id: str, meta: WorkMetadata, targets: List[TrackItem], root_path: Path) -> None:
        """Actually process the download from the queue."""
        
        cover_path = root_path / "cover.jpg"
        if meta.cover_url:
            root_path.mkdir(parents=True, exist_ok=True)
            try:
                # Add 10s timeout to prevent hanging the queue if cover server is blocked
                async def fetch_cover():
                    async with await self.kernel.stream(meta.cover_url) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            with open(cover_path, 'wb') as f:
                                f.write(data)
                
                await asyncio.wait_for(fetch_cover(), timeout=10.0)
            except Exception as e:
                logging.error(f"Failed to fetch cover for {rj_id}: {e}")
                cover_path = None
        
        if self.on_work_status:
            self.on_work_status(rj_id, "Downloading")

        coros = [self.download_file(t, meta, cover_path) for t in targets]
        await asyncio.gather(*coros)
        
        final_size = sum(t.save_path.stat().st_size for t in targets if t.save_path.exists())
        self.db.register(meta, final_size, root_path)
        
        if self.on_work_status:
            self.on_work_status(rj_id, "Completed")
