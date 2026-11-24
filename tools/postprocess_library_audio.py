"""Safely normalize lyric sidecars and synchronize MP3 cover/lyrics assets."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
from typing import Iterator

from core.audio import AudioProcessor
from core.media_assets import find_local_cover

ALBUM_ID = re.compile(r"RJ\d{6,8}", re.I)


def iter_album_directories(roots: list[Path]) -> Iterator[Path]:
    seen: set[str] = set()
    for root in roots:
        if not root.is_dir() or root.is_symlink():
            continue
        for current_root, dir_names, _file_names in os.walk(root, followlinks=False):
            current = Path(current_root)
            dir_names[:] = sorted(
                name for name in dir_names
                if not (current / name).is_symlink()
            )
            if ALBUM_ID.search(current.name):
                key = os.path.normcase(os.path.abspath(current))
                if key not in seen:
                    seen.add(key)
                    yield current
                dir_names[:] = []


def iter_album_files(album: Path) -> Iterator[Path]:
    for current_root, dir_names, file_names in os.walk(album, followlinks=False):
        current = Path(current_root)
        dir_names[:] = sorted(
            name for name in dir_names
            if not (current / name).is_symlink()
        )
        for name in sorted(file_names):
            path = current / name
            if not path.is_symlink() and path.is_file():
                yield path


def process_album(album: Path, execute: bool) -> dict[str, int | str | bool]:
    files = list(iter_album_files(album))
    lyric_sources = [
        path for path in files if path.suffix.casefold() in {".vtt", ".lrc"}
    ]
    vtt_sources = [path for path in lyric_sources if path.suffix.casefold() == ".vtt"]
    canonical_lyrics = {
        path for path in lyric_sources
        if path.suffix.casefold() == ".lrc"
        and AudioProcessor.canonical_lyrics_path(path) == path
    }
    planned_lrc = {
        AudioProcessor.canonical_lyrics_path(path) for path in lyric_sources
    }
    mp3_files = [path for path in files if path.suffix.casefold() == ".mp3"]
    incomplete = any(
        path.suffix.casefold() in {".part", ".crdownload", ".download", ".aria2"}
        for path in files
    )
    if incomplete:
        return {
            "album": str(album),
            "cover_found": False,
            "incomplete_skipped": True,
            "vtt_sources": len(vtt_sources),
            "planned_lrc": len(planned_lrc),
            "converted_or_normalized": 0,
            "conversion_errors": 0,
            "mp3_files": len(mp3_files),
            "mp3_eligible": 0,
            "mp3_updated": 0,
            "mp3_unchanged": 0,
            "mp3_errors": 0,
        }

    converted = 0
    conversion_errors = 0
    if execute:
        for source in sorted(
            lyric_sources,
            key=lambda path: (path.suffix.casefold() != ".vtt", str(path).casefold()),
        ):
            destination = AudioProcessor.prepare_lyrics_sidecar(source)
            if destination is None:
                conversion_errors += 1
            else:
                canonical_lyrics.add(destination)
                if destination != source:
                    converted += 1
    else:
        canonical_lyrics.update(planned_lrc)

    cover = find_local_cover(album)
    eligible = updated = unchanged = tag_errors = 0
    for audio in mp3_files:
        lyric = AudioProcessor.find_matching_lyrics(
            audio, sorted(canonical_lyrics, key=lambda path: str(path).casefold())
        )
        if cover is None and lyric is None:
            continue
        eligible += 1
        if not execute:
            continue
        result = AudioProcessor.sync_mp3_assets(audio, cover, lyric)
        if result is True:
            updated += 1
        elif result is False:
            unchanged += 1
        else:
            tag_errors += 1

    return {
        "album": str(album),
        "cover_found": cover is not None,
        "incomplete_skipped": False,
        "vtt_sources": len(vtt_sources),
        "planned_lrc": len(planned_lrc),
        "converted_or_normalized": converted,
        "conversion_errors": conversion_errors,
        "mp3_files": len(mp3_files),
        "mp3_eligible": eligible,
        "mp3_updated": updated,
        "mp3_unchanged": unchanged,
        "mp3_errors": tag_errors,
    }


def write_status(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temp, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("roots", nargs="+", type=Path)
    parser.add_argument(
        "--execute", action="store_true",
        help="write canonical LRC files and synchronize MP3 APIC/USLT tags",
    )
    parser.add_argument(
        "--status", type=Path,
        default=Path(r"C:\tmp\arsm_audio_postprocess_status.json"),
    )
    args = parser.parse_args()

    totals = {
        "albums": 0,
        "albums_with_cover": 0,
        "vtt_sources": 0,
        "incomplete_skipped": 0,
        "planned_lrc": 0,
        "converted_or_normalized": 0,
        "conversion_errors": 0,
        "mp3_files": 0,
        "mp3_eligible": 0,
        "mp3_updated": 0,
        "mp3_unchanged": 0,
        "mp3_errors": 0,
    }
    payload: dict = {
        "mode": "execute" if args.execute else "dry-run",
        "roots": [str(path) for path in args.roots],
        "state": "running",
        "totals": totals,
        "recent_albums": [],
    }
    write_status(args.status, payload)

    for album in iter_album_directories(args.roots):
        result = process_album(album, args.execute)
        totals["albums"] += 1
        totals["albums_with_cover"] += int(bool(result["cover_found"]))
        totals["incomplete_skipped"] += int(bool(result["incomplete_skipped"]))
        for key in (
            "vtt_sources", "planned_lrc", "converted_or_normalized",
            "conversion_errors", "mp3_files", "mp3_eligible",
            "mp3_updated", "mp3_unchanged", "mp3_errors",
        ):
            totals[key] += int(result[key])
        payload["recent_albums"] = (
            payload["recent_albums"][-19:] + [result]
        )
        write_status(args.status, payload)

    payload["state"] = "completed"
    write_status(args.status, payload)
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 1 if totals["conversion_errors"] or totals["mp3_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
