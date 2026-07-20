"""Snapshot-based resource library scanning and atomic index rebuilds.

The filesystem is scanned without holding a SQLite write transaction.  Only a
complete snapshot is committed, so scan interruptions never leave half-rebuilt
``library_items`` or ``library_index`` tables behind.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
import os
from pathlib import Path
from typing import Iterable, Mapping, Sequence
from uuid import uuid4

AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma",
}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".wmv"}
COVER_NAMES = {
    "cover.jpg", "cover.jpeg", "cover.png", "cover.webp",
    "main.jpg", "main.jpeg", "main.png", "main.webp",
    "package.jpg", "package.jpeg", "package.png", "package.webp",
}
ACTIVE_DOWNLOAD_STATUSES = {"queued", "paused", "downloading", "failed", "resuming"}


class LibraryScanError(RuntimeError):
    """Raised when a complete and trustworthy filesystem snapshot cannot be built."""


@dataclass(frozen=True)
class LibraryScanEntry:
    rj_id: str
    library_path: str
    work_dir: str
    folder_name: str
    total_files: int
    total_size: int
    audio_count: int
    image_count: int
    video_count: int
    other_count: int
    has_audio: int
    has_cover: int
    warnings: tuple[str, ...] = ()

    def to_library_index_row(self, scanned_at: str) -> tuple:
        return (
            self.rj_id,
            self.library_path,
            self.work_dir,
            "found",
            self.total_size,
            self.total_files,
            scanned_at,
        )

    def to_library_item_row(self, run_id: str, scanned_at: str) -> tuple:
        return (
            self.rj_id,
            self.work_dir,
            self.folder_name,
            self.total_files,
            self.total_size,
            self.audio_count,
            self.image_count,
            self.video_count,
            self.other_count,
            self.has_audio,
            self.has_cover,
            json.dumps(list(self.warnings), ensure_ascii=False),
            run_id,
            scanned_at,
        )


@dataclass(frozen=True)
class LibraryScanSnapshot:
    run_id: str
    scanned_at: str
    roots: tuple[str, ...]
    entries: tuple[LibraryScanEntry, ...]
    warnings: tuple[str, ...] = ()

    @property
    def unique_rj_count(self) -> int:
        return len({entry.rj_id for entry in self.entries})

    @property
    def total_files(self) -> int:
        return sum(entry.total_files for entry in self.entries)

    @property
    def total_size(self) -> int:
        return sum(entry.total_size for entry in self.entries)

    def as_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "scanned_at": self.scanned_at,
            "roots": list(self.roots),
            "entries": [asdict(entry) for entry in self.entries],
            "warnings": list(self.warnings),
            "unique_rj_count": self.unique_rj_count,
            "total_files": self.total_files,
            "total_size": self.total_size,
        }


@dataclass
class LibraryRebuildResult:
    success: bool
    run_id: str = ""
    found: int = 0
    entries: int = 0
    indexed: int = 0
    updated: int = 0
    missing: int = 0
    removed_index: int = 0
    warnings: int = 0
    errors: int = 0
    error: str = ""
    snapshot: LibraryScanSnapshot | None = field(default=None, repr=False)

    def as_dict(self) -> dict:
        return {
            "success": self.success,
            "run_id": self.run_id,
            "found": self.found,
            "entries": self.entries,
            "indexed": self.indexed,
            "updated": self.updated,
            "missing": self.missing,
            "removed_index": self.removed_index,
            "warnings": self.warnings,
            "errors": self.errors,
            "error": self.error,
        }


def _normalize_rj_id(name: str) -> str:
    import re

    match = re.search(r"(?:RJ)?(\d{6,8})", str(name or ""), re.IGNORECASE)
    if not match:
        return ""
    return f"RJ{int(match.group(1)):08d}"


def _path_key(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _scan_work_dir(path: Path, *, rj_id: str, library_root: Path) -> LibraryScanEntry:
    audio = image = video = other = total_files = total_size = 0
    has_cover = False
    warning_set: set[str] = set()

    try:
        if path.is_symlink():
            raise LibraryScanError(f"RJ directory is a symbolic link: {path}")
        for current_root, dir_names, file_names in os.walk(path, followlinks=False):
            current = Path(current_root)
            kept_dirs: list[str] = []
            for name in dir_names:
                child = current / name
                if child.is_symlink():
                    warning_set.add("symlink_skipped")
                else:
                    kept_dirs.append(name)
            dir_names[:] = kept_dirs

            for name in file_names:
                file_path = current / name
                if file_path.is_symlink():
                    warning_set.add("symlink_skipped")
                    continue
                try:
                    stat = file_path.stat()
                except OSError as exc:
                    raise LibraryScanError(f"Cannot stat {file_path}: {exc}") from exc
                total_files += 1
                total_size += int(stat.st_size)
                suffix = file_path.suffix.casefold()
                lowered = file_path.name.casefold()
                if suffix in AUDIO_EXTENSIONS:
                    audio += 1
                elif suffix in IMAGE_EXTENSIONS:
                    image += 1
                elif suffix in VIDEO_EXTENSIONS:
                    video += 1
                else:
                    other += 1
                if lowered in COVER_NAMES:
                    has_cover = True
                if suffix == ".part" or lowered.endswith(".part"):
                    warning_set.add("contains_part")
    except PermissionError as exc:
        raise LibraryScanError(f"Permission denied while scanning {path}: {exc}") from exc
    except OSError as exc:
        raise LibraryScanError(f"Filesystem error while scanning {path}: {exc}") from exc

    if audio == 0:
        warning_set.add("no_audio")
    if not has_cover:
        warning_set.add("no_cover")
    if total_files == 0:
        warning_set.add("empty_directory")

    return LibraryScanEntry(
        rj_id=rj_id,
        library_path=str(library_root),
        work_dir=str(path),
        folder_name=path.name,
        total_files=total_files,
        total_size=total_size,
        audio_count=audio,
        image_count=image,
        video_count=video,
        other_count=other,
        has_audio=int(audio > 0),
        has_cover=int(has_cover),
        warnings=tuple(sorted(warning_set)),
    )


def _discover_rj_directories(root: Path, max_depth: int = 2) -> list[Path]:
    discovered: list[Path] = []
    queue = deque([(root, 0)])
    while queue:
        current, depth = queue.popleft()
        try:
            children = sorted(current.iterdir(), key=lambda item: item.name.casefold())
        except PermissionError as exc:
            raise LibraryScanError(f"Permission denied while listing {current}: {exc}") from exc
        except OSError as exc:
            raise LibraryScanError(f"Cannot list {current}: {exc}") from exc
        for child in children:
            if child.is_symlink():
                continue
            if not child.is_dir():
                continue
            if _normalize_rj_id(child.name):
                discovered.append(child)
                continue
            if depth + 1 < max_depth:
                queue.append((child, depth + 1))
    return discovered


def scan_library_snapshot(paths: Sequence[str | Path], *, max_depth: int = 2) -> LibraryScanSnapshot:
    """Build a complete immutable filesystem snapshot without changing SQLite."""
    roots: list[str] = []
    warnings: list[str] = []
    entries: list[LibraryScanEntry] = []
    seen_work_dirs: set[str] = set()

    for raw_path in paths:
        value = str(raw_path or "").strip()
        if not value:
            continue
        raw_root = Path(value).expanduser()
        if raw_root.is_symlink():
            raise LibraryScanError(f"Library root is a symbolic link: {raw_root}")
        root = raw_root.resolve()
        roots.append(str(root))
        if not root.exists():
            warnings.append(f"missing_root:{root}")
            continue
        if not root.is_dir():
            raise LibraryScanError(f"Library root is not a directory: {root}")
        for work_dir in _discover_rj_directories(root, max_depth=max_depth):
            key = _path_key(work_dir)
            if key in seen_work_dirs:
                continue
            seen_work_dirs.add(key)
            rj_id = _normalize_rj_id(work_dir.name)
            entries.append(_scan_work_dir(work_dir, rj_id=rj_id, library_root=root))

    if not roots:
        raise LibraryScanError("No library paths configured")
    if not any(Path(root).exists() for root in roots):
        raise LibraryScanError("None of the configured library paths exist")

    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.rj_id] = counts.get(entry.rj_id, 0) + 1
    if any(count > 1 for count in counts.values()):
        entries = [
            LibraryScanEntry(
                **{
                    **asdict(entry),
                    "warnings": tuple(sorted(
                        set(entry.warnings)
                        | ({"duplicate_rj"} if counts[entry.rj_id] > 1 else set())
                    )),
                }
            )
            for entry in entries
        ]

    entries.sort(key=lambda item: (item.rj_id, _path_key(item.work_dir)))
    return LibraryScanSnapshot(
        run_id=uuid4().hex,
        scanned_at=datetime.now().isoformat(timespec="seconds"),
        roots=tuple(roots),
        entries=tuple(entries),
        warnings=tuple(warnings),
    )


def choose_canonical_entries(
    snapshot: LibraryScanSnapshot,
    preferred_paths: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, LibraryScanEntry]:
    """Choose one work-level card per RJ while retaining all index entries."""
    preferred_paths = preferred_paths or {}
    grouped: dict[str, list[LibraryScanEntry]] = {}
    for entry in snapshot.entries:
        grouped.setdefault(entry.rj_id, []).append(entry)

    selected: dict[str, LibraryScanEntry] = {}
    for rj_id, entries in grouped.items():
        by_key = {_path_key(entry.work_dir): entry for entry in entries}
        chosen = None
        for candidate in preferred_paths.get(rj_id, ()):  # works path, then previous item path
            chosen = by_key.get(_path_key(candidate))
            if chosen is not None:
                break
        selected[rj_id] = chosen or entries[0]
    return selected


def flatten_metadata_track_titles(tracks: Iterable[dict]) -> list[str]:
    """Return all file titles from arbitrarily nested ASMR.one track trees."""
    result: list[str] = []
    stack = list(reversed(list(tracks or [])))
    while stack:
        item = stack.pop()
        if not isinstance(item, dict):
            continue
        children = item.get("children") or item.get("tracks") or []
        if isinstance(children, list):
            stack.extend(reversed(children))
        if str(item.get("type") or "").casefold() == "folder":
            continue
        title = str(item.get("title") or item.get("name") or "").strip()
        if title:
            result.append(title)
    return result
