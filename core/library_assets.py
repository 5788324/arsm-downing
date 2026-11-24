"""Plan and apply per-album sidecar and MP3 repairs."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path, PurePosixPath
import json
import os
import re
import shutil
import tempfile
import time
from zipfile import BadZipFile, ZipFile

from mutagen.mp3 import MP3
from PIL import Image

from core.audio import AudioProcessor
from core.library_rebuild import AUDIO_EXTENSIONS
from core.local_file_validation import validate_completed_local_file
from core.media_assets import find_local_cover

_SUBTITLE_LIMIT = 2 * 1024 * 1024


@dataclass(frozen=True)
class SubtitleMatch:
    source: str
    destination: Path
    text: str


@dataclass(frozen=True)
class AlbumAssets:
    subtitles: tuple[SubtitleMatch, ...]
    unmatched: int
    audio: tuple[Path, ...]
    mp3_tasks: tuple[tuple[Path, Path | None, bool], ...]
    cover: Path | None
    archives: int


_ARCHIVE_NAME = re.compile(r"RJ([0-9]{6,8})\.zip", re.IGNORECASE)


@lru_cache(maxsize=4)
def _archive_catalog(location: Path, interval: int) -> dict[str, tuple[Path, ...]]:
    grouped = defaultdict(list)
    for current, dirs, names in os.walk(location):
        directory = Path(current)
        dirs[:] = [name for name in dirs if not (directory / name).is_symlink()
                   and not os.path.isjunction(directory / name)]
        for name in names:
            match = _ARCHIVE_NAME.fullmatch(name)
            if match:
                grouped[f"RJ{int(match.group(1)):08d}"].append(directory / name)
    return {rid: tuple(files) for rid, files in grouped.items()}


def clear_subtitle_catalog_cache() -> None:
    _archive_catalog.cache_clear()


def subtitle_candidates(archive_dir: str, known_ids: set[str], search: str) -> list[str]:
    if not archive_dir:
        return []
    ids = _archive_catalog(Path(archive_dir), int(time.monotonic() // 60)).keys()
    query = search.strip().upper()
    return sorted((rid for rid in ids - known_ids if query in rid), reverse=True)


def _album_files(root: Path):
    for current, dirs, names in os.walk(root):
        folder = Path(current)
        dirs[:] = [name for name in dirs if not (folder / name).is_symlink()
                   and not os.path.isjunction(folder / name)]
        for name in names:
            path = folder / name
            if not path.is_symlink() and path.is_file():
                yield path


def _read_small(path: Path) -> bytes:
    with path.open("rb") as stream:
        return stream.read(_SUBTITLE_LIMIT + 1)


def _decode_subtitle(name: str, payload: bytes) -> str:
    if len(payload) > _SUBTITLE_LIMIT:
        return ""
    try:
        text = AudioProcessor._decode_text(payload)
    except UnicodeError:
        return ""
    if Path(name).suffix.casefold() == ".vtt":
        return AudioProcessor.vtt_to_lrc_text(text)
    if "\x00" in text or "\ufffd" in text:
        return ""
    return AudioProcessor._t2s.convert(text).strip()


def _key(path: Path) -> str:
    stem = AudioProcessor.canonical_lyrics_path(path).stem
    return AudioProcessor._t2s.convert(stem).strip().casefold()


def _se_version(parts: tuple[str, ...]) -> str:
    for part in reversed(parts):
        name = re.sub(r"[\W_]+", "", AudioProcessor._t2s.convert(part).casefold())
        if name in {"nose", "se无", "无se", "无se音", "无se版", "无音效", "无音效版"}:
            return "no_se"
        if name in {"se", "withse", "有se", "有se音", "有se版", "有音效", "有音效版"}:
            return "se"
    return ""


def _same_subtitle_version(source_parts: tuple[str, ...],
                           target_parts: tuple[str, ...]) -> bool:
    source_version = _se_version(source_parts)
    target_version = _se_version(target_parts)
    return not source_version or not target_version or source_version == target_version


def _archives(location: Path, rj_id: str):
    paths = _archive_catalog(location, int(time.monotonic() // 60)).get(rj_id, ())
    for path in paths:
        if not path.is_symlink():
            yield path


def inspect_album_assets(root: Path, rj_id: str, archive_dir: str,
                         *, include_tags: bool = True, verify_audio: bool = True,
                         source_paths: list[Path] | None = None) -> AlbumAssets:
    files = sorted(_album_files(root) if source_paths is None else source_paths)
    audio = tuple(path for path in files if path.suffix.casefold() in AUDIO_EXTENSIONS
                  and (not verify_audio or validate_completed_local_file(path)[0]))
    by_stem = defaultdict(set)
    for path in audio:
        by_stem[_key(path)].add(path.with_suffix(".lrc"))
    candidates: dict[Path, SubtitleMatch] = {}
    ambiguous: set[Path] = set()
    unmatched = 0

    for path in files:
        if path.suffix.casefold() not in {".lrc", ".vtt"}:
            continue
        destination = AudioProcessor.canonical_lyrics_path(path)
        if destination.exists():
            continue
        text = _decode_subtitle(path.name, _read_small(path))
        if text:
            candidates[destination] = SubtitleMatch(path.name, destination, text)

    packs = sorted(_archives(Path(archive_dir), rj_id)) if archive_dir else []
    for pack in packs:
        try:
            with ZipFile(pack) as bundle:
                for item in bundle.infolist():
                    relative = PurePosixPath(item.filename.replace("\\", "/"))
                    if (item.is_dir() or relative.is_absolute() or ".." in relative.parts
                            or relative.suffix.casefold() not in {".lrc", ".vtt"}
                            or item.file_size > _SUBTITLE_LIMIT):
                        continue
                    matches = {
                        target for target in by_stem.get(_key(Path(relative.name)), set())
                        if target.is_relative_to(root)
                        and _same_subtitle_version(relative.parts[:-1],
                                                   target.relative_to(root).parts[:-1])
                    }
                    if len(matches) > 1 and relative.parent.name:
                        matches = {p for p in matches
                                   if p.parent.name.casefold() == relative.parent.name.casefold()}
                    if len(matches) != 1:
                        unmatched += 1
                        continue
                    destination, = matches
                    if destination.exists() or destination in ambiguous:
                        continue
                    with bundle.open(item) as stream:
                        text = _decode_subtitle(relative.name, stream.read(_SUBTITLE_LIMIT + 1))
                    if not text:
                        unmatched += 1
                        continue
                    existing = candidates.get(destination)
                    if existing and existing.text.strip() != text.strip():
                        del candidates[destination]
                        ambiguous.add(destination)
                        unmatched += 1
                    else:
                        candidates[destination] = SubtitleMatch(relative.name, destination, text)
        except (BadZipFile, OSError, RuntimeError, NotImplementedError):
            unmatched += 1

    cover = None
    tasks = []
    if include_tags:
        try:
            cover = find_local_cover(root)
            if cover is not None:
                with Image.open(cover) as image:
                    image.verify()
                if not AudioProcessor.cover_mime(cover):
                    cover = None
        except (OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            cover = None
        lyrics = defaultdict(list)
        for path in files:
            if path.suffix.casefold() == ".lrc" and path.stat().st_size <= _SUBTITLE_LIMIT:
                lyrics[_key(path)].append(path)
        for path in audio:
            if path.suffix.casefold() != ".mp3":
                continue
            options = lyrics.get(_key(path), [])
            same_folder = [candidate for candidate in options if candidate.parent == path.parent]
            options = same_folder or options
            lyric = options[0] if len(options) == 1 else None
            try:
                tags = MP3(path).tags
                need_cover = bool(cover and not (tags and any(
                    pic.type == 3 and pic.data for pic in tags.getall("APIC"))))
                need_lyrics = bool(lyric and not (tags and (
                    tags.getall("USLT") or tags.getall("SYLT"))))
            except Exception:
                continue
            if need_cover or need_lyrics:
                tasks.append((path, lyric if need_lyrics else None, need_cover))
    return AlbumAssets(tuple(candidates.values()), unmatched, audio, tuple(tasks), cover, len(packs))


def _write_new_lyric(destination: Path, text: str) -> bool:
    """Create a sidecar without replacing an existing file on replay."""
    try:
        stream = destination.open("x", encoding="utf-8", newline="\n")
    except FileExistsError:
        return False
    try:
        with stream:
            stream.write(text.rstrip() + "\n")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return True


def materialize_track_lyrics(root: Path, rj_id: str, files: list[Path],
                             lyric_paths: list[Path], archive_dir: str) -> dict[Path, Path]:
    """Place matched LRC next to completed audio and return exact tag sources."""
    album = root.resolve()
    tracks = [path for path in dict.fromkeys(files)
              if path.suffix.casefold() in AUDIO_EXTENSIONS]
    destinations: dict[str, set[Path]] = defaultdict(set)
    for track in tracks:
        destinations[_key(track)].add(track.with_suffix(".lrc"))
    sources: dict[str, set[Path]] = defaultdict(set)
    for path in lyric_paths:
        sources[_key(path)].add(path)
    unresolved = set()
    matched = {}
    for track in tracks:
        target = track.with_suffix(".lrc")
        if target.is_file() and not target.is_symlink():
            if _decode_subtitle(target.name, _read_small(target)):
                matched[track] = target
            continue
        if not target.resolve().is_relative_to(album):
            continue
        key = _key(track)
        options = sources[key]
        local = {source for source in options if source.parent == track.parent}
        if local:
            options = local
        elif len(destinations[key]) != 1:
            options = set()
        if len(options) == 1:
            source, = options
            resolved = source.resolve()
            if (not source.is_symlink() and resolved.is_relative_to(album)
                    and _same_subtitle_version(resolved.relative_to(album).parts[:-1],
                                               target.resolve().relative_to(album).parts[:-1])):
                text = _decode_subtitle(source.name, _read_small(source))
                if text and _write_new_lyric(target, text):
                    matched[track] = target
                    continue
        unresolved.add(target)
    if archive_dir and unresolved:
        plan = inspect_album_assets(
            root, rj_id, archive_dir, include_tags=False, verify_audio=False,
            source_paths=files,
        )
        for entry in plan.subtitles:
            if entry.destination in unresolved:
                _write_new_lyric(entry.destination, entry.text)
        for track in tracks:
            target = track.with_suffix(".lrc")
            if target in unresolved and target.is_file() and not target.is_symlink():
                if _decode_subtitle(target.name, _read_small(target)):
                    matched[track] = target
    return matched


def apply_subtitles(db, rj_id: str, root: Path, plan: AlbumAssets) -> int:
    created: list[Path] = []
    def write(conn):
        conn.execute("BEGIN IMMEDIATE")
        _guard_album(conn, rj_id, root)
        for entry in plan.subtitles:
            if not entry.destination.resolve().is_relative_to(root.resolve()):
                raise ValueError("字幕目标不在专辑目录")
            if _write_new_lyric(entry.destination, entry.text):
                created.append(entry.destination)
    try:
        db._write(write)
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return len(created)


def _guard_album(conn, rj_id: str, root: Path) -> None:
    row = conn.execute("SELECT folder_path FROM library_items WHERE rj_id=?", (rj_id,)).fetchone()
    if not row or not row[0] or Path(row[0]).resolve() != root.resolve():
        raise ValueError("专辑目录已变更，请重新打开详情")
    if conn.execute("SELECT 1 FROM downloads WHERE rj_id=? AND status IN "
                    "('queued','downloading','resuming') LIMIT 1", (rj_id,)).fetchone():
        raise ValueError("专辑仍在下载，请稍后重试")


def fill_mp3_tags(db, rj_id: str, root: Path, plan: AlbumAssets, backups: Path) -> int:
    if not plan.mp3_tasks:
        return 0
    backups.mkdir(parents=True, exist_ok=True)
    backup_dir = Path(tempfile.mkdtemp(prefix=f"{rj_id}-", dir=backups))
    count = 0
    for path, lyric, need_cover in plan.mp3_tasks:
        initial = path.stat()
        backup = backup_dir / path.relative_to(root)
        backup.parent.mkdir(parents=True, exist_ok=True)
        rows = [dict(row) for row in db.get_downloads_by_rj(rj_id)
                if str(row["local_path"]).casefold() == str(path).casefold()]
        backup.with_name(backup.name + ".records.json").write_text(
            json.dumps(rows, ensure_ascii=False), encoding="utf8")
        shutil.copy2(path, backup)
        fd, temp_name = tempfile.mkstemp(prefix=".arsm-tags-", suffix=".mp3", dir=path.parent)
        os.close(fd)
        temporary = Path(temp_name)
        replaced = False
        try:
            shutil.copy2(backup, temporary)
            if AudioProcessor.sync_mp3_assets(temporary, plan.cover if need_cover else None, lyric) is not True:
                continue
            tags = MP3(temporary).tags
            if (need_cover and not tags.getall("APIC")) or (lyric and not tags.getall("USLT")):
                raise ValueError("MP3 标签读回校验失败")
            new_size = temporary.stat().st_size

            def commit(conn):
                nonlocal replaced
                conn.execute("BEGIN IMMEDIATE")
                _guard_album(conn, rj_id, root)
                current = path.stat()
                if (current.st_size, current.st_mtime_ns) != (initial.st_size, initial.st_mtime_ns):
                    raise ValueError("音频在处理期间已变更")
                os.replace(temporary, path)
                replaced = True
                conn.execute(
                    "UPDATE downloads SET downloaded_bytes=?,total_bytes=?,updated_at=? "
                    "WHERE rj_id=? AND local_path=? COLLATE NOCASE "
                    "AND status IN ('completed','registered')",
                    (new_size, new_size, datetime.now().isoformat(), rj_id, str(path)))
            db._write(commit)
            count += 1
        except BaseException:
            if replaced:
                shutil.copy2(backup, temporary)
                os.replace(temporary, path)
            raise
        finally:
            temporary.unlink(missing_ok=True)
    return count
