from __future__ import annotations

import base64
import html
import logging
import os
from pathlib import Path
import re
from typing import Optional

import mutagen
from mutagen.aiff import AIFF
from mutagen.asf import ASF
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1, TPUB, USLT
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE
from opencc import OpenCC

from core.models import WorkMetadata

logger = logging.getLogger("echovault.audio")


class AudioProcessor:
    """Apply common work metadata without making download success depend on tags."""

    SUPPORTED_EXTENSIONS = {
        ".mp3", ".flac", ".ogg", ".oga", ".opus",
        ".m4a", ".m4b", ".mp4", ".wav", ".wave", ".aif", ".aiff",
        ".wma", ".asf",
    }
    _t2s = OpenCC("t2s")
    _VTT_TIMESTAMP = re.compile(
        r"^(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{1,3})"
    )

    @staticmethod
    def apply_tags(path: Path, meta: WorkMetadata, cover: Optional[Path],
                   lyrics: Optional[Path] = None) -> bool:
        """Apply metadata and return whether the format was tagged successfully.

        Tagging remains best-effort: callers may log the result, but a corrupt or
        unsupported tag container must never turn a completed audio download into
        a failed download.
        """
        if not path.is_file():
            return False

        ext = path.suffix.lower()
        try:
            if ext == ".mp3":
                AudioProcessor._tag_mp3(path, meta, cover, lyrics)
            elif ext == ".flac":
                AudioProcessor._tag_flac(path, meta, cover)
            elif ext in {".ogg", ".oga"}:
                AudioProcessor._tag_vorbis(path, meta, cover)
            elif ext == ".opus":
                AudioProcessor._tag_opus(path, meta, cover)
            elif ext in {".m4a", ".m4b", ".mp4"}:
                AudioProcessor._tag_mp4(path, meta, cover)
            elif ext in {".wav", ".wave"}:
                AudioProcessor._tag_id3_container(WAVE(str(path)), path, meta, cover)
            elif ext in {".aif", ".aiff"}:
                AudioProcessor._tag_id3_container(AIFF(str(path)), path, meta, cover)
            elif ext in {".wma", ".asf"}:
                AudioProcessor._tag_asf(path, meta)
            else:
                logger.debug("Tagging skipped for unsupported format: %s", path)
                return False
            return True
        except Exception as exc:
            logger.warning("Failed to tag %s: %s", path, exc)
            return False

    @staticmethod
    def cover_mime(cover: Optional[Path]) -> Optional[str]:
        if not cover or not cover.is_file():
            return None
        try:
            with cover.open("rb") as stream:
                header = stream.read(16)
        except OSError:
            return None
        if header.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if header.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if header.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"
        if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
            return "image/webp"
        return None

    @staticmethod
    def _artist(meta: WorkMetadata) -> str:
        return ", ".join(meta.cv) if meta.cv else "Unknown"

    @staticmethod
    def _picture(cover: Optional[Path]) -> Optional[Picture]:
        mime = AudioProcessor.cover_mime(cover)
        if not cover or not mime:
            return None
        picture = Picture()
        picture.type = 3
        picture.mime = mime
        picture.desc = "Cover"
        picture.data = cover.read_bytes()
        return picture

    @staticmethod
    def is_tagged_mp3(path: Path) -> bool:
        """Recognize a completed MP3 whose local size includes managed tags."""
        if path.suffix.lower() != ".mp3" or not path.is_file():
            return False
        try:
            audio = MP3(str(path), ID3=ID3)
            return bool(audio.tags and audio.tags.getall("APIC"))
        except Exception:
            return False

    @staticmethod
    def canonical_lyrics_path(path: Path, suffix: str = ".lrc") -> Path:
        """Strip a trailing audio extension from a lyric sidecar stem."""
        stem = path.stem
        while Path(stem).suffix.casefold() in AudioProcessor.SUPPORTED_EXTENSIONS:
            stem = Path(stem).stem
        normalized_suffix = suffix if suffix.startswith(".") else f".{suffix}"
        return path.with_name(f"{stem}{normalized_suffix.lower()}")

    @staticmethod
    def _decode_text(payload: bytes) -> str:
        for encoding in ("utf-8-sig", "utf-16", "gb18030", "big5"):
            try:
                return payload.decode(encoding)
            except UnicodeDecodeError:
                continue
        return payload.decode("utf-8", errors="replace")

    @staticmethod
    def vtt_to_lrc_text(text: str) -> str:
        """Convert WebVTT cues to Simplified-Chinese LRC lines."""
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        output: list[str] = []
        index = 0
        while index < len(lines):
            line = lines[index].strip()
            if "-->" not in line:
                index += 1
                continue
            start = line.split("-->", 1)[0].strip()
            match = AudioProcessor._VTT_TIMESTAMP.match(start)
            index += 1
            if not match:
                continue
            hours = int(match.group(1) or 0)
            minutes = int(match.group(2)) + hours * 60
            seconds = int(match.group(3))
            millis = int(match.group(4).ljust(3, "0")[:3])
            stamp = f"[{minutes:02d}:{seconds:02d}.{millis // 10:02d}]"
            while index < len(lines) and lines[index].strip():
                cue = re.sub(r"<[^>]+>", "", lines[index]).strip()
                cue = html.unescape(cue)
                if cue:
                    output.append(stamp + AudioProcessor._t2s.convert(cue))
                index += 1
        return "\n".join(output)

    @staticmethod
    def prepare_lyrics_sidecar(path: Path) -> Optional[Path]:
        """Create a canonical LRC while preserving the tracked source file."""
        if not path.is_file() or path.suffix.casefold() not in {".lrc", ".vtt"}:
            return None
        destination = AudioProcessor.canonical_lyrics_path(path, ".lrc")
        if path.suffix.casefold() == ".lrc" and destination == path:
            return path
        try:
            text = AudioProcessor._decode_text(path.read_bytes())
            if path.suffix.casefold() == ".vtt":
                text = AudioProcessor.vtt_to_lrc_text(text)
            else:
                text = AudioProcessor._t2s.convert(text)
            if not text.strip():
                return None
            temp = destination.with_name(destination.name + ".tmp")
            temp.write_text(text.rstrip() + "\n", encoding="utf-8")
            os.replace(temp, destination)
            return destination
        except OSError as exc:
            logger.warning("Failed to prepare lyric sidecar %s: %s", path, exc)
            return None

    @staticmethod
    def read_lyrics(path: Optional[Path]) -> Optional[str]:
        """Read an LRC sidecar and normalize Traditional Chinese to Simplified."""
        if not path or not path.is_file():
            return None
        payload = path.read_bytes()
        text = AudioProcessor._decode_text(payload)
        return AudioProcessor._t2s.convert(text)

    @staticmethod
    def find_matching_lyrics(audio: Path, candidates: list[Path]) -> Optional[Path]:
        """Choose the nearest same-stem LRC without crossing locale folders."""
        matches = [
            candidate for candidate in candidates
            if candidate.stem.casefold() == audio.stem.casefold()
        ]
        if not matches:
            return None

        def distance(candidate: Path) -> tuple[int, str]:
            audio_parts = audio.parent.parts
            lyric_parts = candidate.parent.parts
            shared = 0
            for left, right in zip(audio_parts, lyric_parts):
                if left.casefold() != right.casefold():
                    break
                shared += 1
            return (
                len(audio_parts) + len(lyric_parts) - 2 * shared,
                str(candidate).casefold(),
            )

        return min(matches, key=distance)

    @staticmethod
    def _write_id3(tags: ID3, path: Path, meta: WorkMetadata,
                   cover: Optional[Path], lyrics: Optional[Path] = None) -> None:
        for key in ("TIT2", "TPE1", "TALB", "TPUB", "APIC"):
            tags.delall(key)
        tags.add(TIT2(encoding=3, text=[path.stem]))
        tags.add(TPE1(encoding=3, text=[AudioProcessor._artist(meta)]))
        tags.add(TALB(encoding=3, text=[meta.title]))
        if meta.circle:
            tags.add(TPUB(encoding=3, text=[meta.circle]))
        picture = AudioProcessor._picture(cover)
        if picture is not None:
            tags.add(APIC(
                encoding=3,
                mime=picture.mime,
                type=3,
                desc="Cover",
                data=picture.data,
            ))
        lyrics_text = AudioProcessor.read_lyrics(lyrics)
        if lyrics_text is not None:
            tags.delall("USLT")
            tags.add(USLT(
                encoding=3,
                lang="zho",
                desc="Simplified Chinese LRC",
                text=lyrics_text,
            ))

    @staticmethod
    def _tag_mp3(path: Path, meta: WorkMetadata, cover: Optional[Path],
                 lyrics: Optional[Path] = None) -> None:
        audio = MP3(str(path), ID3=ID3)
        if audio.tags is None:
            audio.add_tags()
        AudioProcessor._write_id3(audio.tags, path, meta, cover, lyrics)
        audio.save(v2_version=3)

    @staticmethod
    def _tag_id3_container(audio, path: Path, meta: WorkMetadata, cover: Optional[Path]) -> None:
        if audio.tags is None:
            audio.add_tags()
        AudioProcessor._write_id3(audio.tags, path, meta, cover)
        audio.save()

    @staticmethod
    def _set_vorbis_text(audio, path: Path, meta: WorkMetadata) -> None:
        audio["title"] = [path.stem]
        audio["artist"] = [AudioProcessor._artist(meta)]
        audio["album"] = [meta.title]
        if meta.circle:
            audio["organization"] = [meta.circle]

    @staticmethod
    def _set_vorbis_cover(audio, cover: Optional[Path]) -> None:
        picture = AudioProcessor._picture(cover)
        if picture is None:
            audio.pop("metadata_block_picture", None)
            return
        encoded = base64.b64encode(picture.write()).decode("ascii")
        audio["metadata_block_picture"] = [encoded]

    @staticmethod
    def _tag_vorbis(path: Path, meta: WorkMetadata, cover: Optional[Path]) -> None:
        audio = OggVorbis(str(path))
        AudioProcessor._set_vorbis_text(audio, path, meta)
        AudioProcessor._set_vorbis_cover(audio, cover)
        audio.save()

    @staticmethod
    def _tag_opus(path: Path, meta: WorkMetadata, cover: Optional[Path]) -> None:
        audio = OggOpus(str(path))
        AudioProcessor._set_vorbis_text(audio, path, meta)
        AudioProcessor._set_vorbis_cover(audio, cover)
        audio.save()

    @staticmethod
    def _tag_flac(path: Path, meta: WorkMetadata, cover: Optional[Path]) -> None:
        audio = FLAC(str(path))
        AudioProcessor._set_vorbis_text(audio, path, meta)
        audio.clear_pictures()
        picture = AudioProcessor._picture(cover)
        if picture is not None:
            audio.add_picture(picture)
        audio.save()

    @staticmethod
    def _tag_mp4(path: Path, meta: WorkMetadata, cover: Optional[Path]) -> None:
        audio = MP4(str(path))
        if audio.tags is None:
            audio.add_tags()
        audio["\xa9nam"] = [path.stem]
        audio["\xa9ART"] = [AudioProcessor._artist(meta)]
        audio["\xa9alb"] = [meta.title]
        if meta.circle:
            audio["----:com.apple.iTunes:ORGANIZATION"] = [meta.circle.encode("utf-8")]

        mime = AudioProcessor.cover_mime(cover)
        if cover and mime in {"image/jpeg", "image/png"}:
            image_format = (
                MP4Cover.FORMAT_PNG if mime == "image/png" else MP4Cover.FORMAT_JPEG
            )
            audio["covr"] = [MP4Cover(cover.read_bytes(), imageformat=image_format)]
        elif "covr" in audio:
            del audio["covr"]
        audio.save()

    @staticmethod
    def _tag_asf(path: Path, meta: WorkMetadata) -> None:
        audio = ASF(str(path))
        audio["Title"] = [path.stem]
        audio["Author"] = [AudioProcessor._artist(meta)]
        audio["WM/AlbumTitle"] = [meta.title]
        if meta.circle:
            audio["WM/Publisher"] = [meta.circle]
        audio.save()
