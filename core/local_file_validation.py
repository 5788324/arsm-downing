"""Conservative validation for oversized files found during queue recovery.

The downloader normally requires an exact byte count. A previously completed
file can legitimately be larger when local post-processing or an upstream
metadata revision changed the recorded size. These checks intentionally only
recognize formats that can be validated without changing the file.
"""

from __future__ import annotations

from pathlib import Path

import mutagen
from PIL import Image


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
TEXT_EXTENSIONS = {".txt", ".lrc", ".vtt", ".srt", ".cue"}
AUDIO_EXTENSIONS = {
    ".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".m4b", ".mp4",
    ".wav", ".wave", ".aif", ".aiff", ".wma", ".asf",
}



def _content_suffix(path: Path) -> str:
    """Return the original suffix when validating a downloader .part file."""
    suffix = path.suffix.casefold()
    if suffix == ".part":
        return path.with_suffix("").suffix.casefold()
    return suffix


def validate_completed_local_file(path: Path) -> tuple[bool, str]:
    """Return whether an existing file is structurally usable.

    This is a recovery check, not a checksum replacement. Unknown formats and
    malformed files remain in manual review instead of being accepted by size alone.
    """


    if not path.is_file() or path.stat().st_size <= 0:
        return False, "missing_or_empty"

    suffix = _content_suffix(path)
    try:
        if suffix in IMAGE_EXTENSIONS:
            with Image.open(path) as image:
                width, height = image.size
                image.verify()
            return (width > 0 and height > 0), "valid_image"

        if suffix in AUDIO_EXTENSIONS:
            if path.suffix.casefold() == ".part":
                with path.open("rb") as stream:
                    media = mutagen.File(stream)
            else:
                media = mutagen.File(str(path))
            info = getattr(media, "info", None) if media is not None else None
            length = getattr(info, "length", None)
            if info is not None and (length is None or float(length) >= 0):
                return True, "valid_media"
            return False, "invalid_media"

        if suffix in TEXT_EXTENSIONS:
            with path.open("rb") as stream:
                sample = stream.read(256 * 1024)
            if not sample or b"\x00" in sample:
                return False, "invalid_text"
            for encoding in ("utf-8-sig", "gb18030", "big5", "shift_jis"):
                try:
                    sample.decode(encoding)
                    return True, "valid_text"
                except UnicodeDecodeError:
                    continue
            return False, "invalid_text_encoding"
    except (OSError, ValueError, TypeError, mutagen.MutagenError):
        return False, "validation_failed"

    return False, "unsupported_format"
