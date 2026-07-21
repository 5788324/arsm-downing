from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Optional

import mutagen
from mutagen.aiff import AIFF
from mutagen.asf import ASF
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1, TPUB
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE

from core.models import WorkMetadata

logger = logging.getLogger("echovault.audio")


class AudioProcessor:
    """Apply common work metadata without making download success depend on tags."""

    SUPPORTED_EXTENSIONS = {
        ".mp3", ".flac", ".ogg", ".oga", ".opus",
        ".m4a", ".m4b", ".mp4", ".wav", ".wave", ".aif", ".aiff",
        ".wma", ".asf",
    }

    @staticmethod
    def apply_tags(path: Path, meta: WorkMetadata, cover: Optional[Path]) -> bool:
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
                AudioProcessor._tag_mp3(path, meta, cover)
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
    def _write_id3(tags: ID3, path: Path, meta: WorkMetadata, cover: Optional[Path]) -> None:
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

    @staticmethod
    def _tag_mp3(path: Path, meta: WorkMetadata, cover: Optional[Path]) -> None:
        audio = MP3(str(path), ID3=ID3)
        if audio.tags is None:
            audio.add_tags()
        AudioProcessor._write_id3(audio.tags, path, meta, cover)
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
