"""Conservative validation for oversized files found during queue recovery.

The downloader normally requires an exact byte count. A previously completed
file can legitimately be larger when local post-processing or an upstream
metadata revision changed the recorded size. These checks intentionally only
recognize formats that can be validated without changing the file.
"""

from __future__ import annotations

import codecs
import struct
from collections import defaultdict, deque
from pathlib import Path
from typing import BinaryIO

import mutagen
from PIL import Image


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
TEXT_EXTENSIONS = {".txt", ".lrc", ".vtt", ".srt", ".cue"}
SOURCE_EMPTY_TXT = "source_empty_txt"


def is_confirmed_empty_txt(path: Path, expected_size: int, evidence: str) -> bool:
    """Recognize a real zero-byte TXT only with persisted source confirmation."""
    try:
        return (evidence == SOURCE_EMPTY_TXT and expected_size == 0
                and path.suffix.casefold() == ".txt" and path.is_file()
                and path.stat().st_size == 0)
    except OSError:
        return False
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


def _validate_utf16_text(stream: BinaryIO, sample: bytes) -> tuple[bool, str]:
    """Validate BOM-marked text to EOF, including split code units and tails."""
    decoder = codecs.getincrementaldecoder("utf-16")()
    has_content = False
    try:
        while True:
            text = decoder.decode(sample, final=not sample)
            if any((ord(char) < 32 and char not in "\t\r\n")
                   or 127 <= ord(char) <= 159 for char in text):
                return False, "invalid_text"
            has_content = has_content or bool(text.strip().strip("\ufeff").strip())
            if not sample:
                return (True, "valid_text") if has_content else (False, "invalid_text")
            sample = stream.read(256 * 1024)
    except UnicodeDecodeError:
        return False, "invalid_text_encoding"


def _validate_rf64(stream: BinaryIO, file_size: int) -> tuple[bool, str]:
    """Validate RF64 sizes and required chunks without decoding the audio."""
    header = stream.read(48)
    if len(header) != 48 or header[8:16] != b"WAVEds64":
        return False, "invalid_wave_header"
    ds64_size, riff_size, data_size, _, table_count = struct.unpack_from("<IQQQI", header, 16)
    if (ds64_size < 28 or ds64_size < 28 + 12 * table_count
            or 20 + ds64_size > file_size):
        return False, "invalid_wave_header"

    declared = int.from_bytes(header[4:8], "little")
    if declared == 0xffffffff:
        declared = riff_size
    if declared + 8 != file_size:
        return False, "wave_length_mismatch"

    sizes = defaultdict(deque)
    for _ in range(table_count):
        entry = stream.read(12)
        if len(entry) != 12:
            return False, "invalid_wave_header"
        chunk_id, size = struct.unpack("<4sQ", entry)
        sizes[chunk_id].append(size)

    offset = 20 + ds64_size + ds64_size % 2
    has_format = has_audio = False
    while offset + 8 <= file_size:
        stream.seek(offset)
        chunk = stream.read(8)
        if len(chunk) != 8:
            return False, "invalid_wave_chunk"
        name, size = struct.unpack("<4sI", chunk)
        if size == 0xffffffff:
            if name == b"data" and not has_audio:
                size = data_size
            elif sizes.get(name):
                size = sizes[name].popleft()
            else:
                return False, "invalid_wave_chunk"
        if name == b"fmt ":
            has_format = size >= 16
        elif name == b"data":
            has_audio = has_format and size > 0
        offset += 8 + size + size % 2
    if offset != file_size or not (has_format and has_audio):
        return False, "invalid_wave_chunk"
    return True, "valid_media"


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
            if suffix in {".wav", ".wave"}:
                with path.open("rb") as stream:
                    header = stream.read(12)
                    if header[:4] in {b"RF64", b"BW64"}:
                        stream.seek(0)
                        return _validate_rf64(stream, path.stat().st_size)
                    if (len(header) == 12 and header[:4] == b"RIFF"
                            and header[8:] == b"WAVE"
                            and int.from_bytes(header[4:8], "little") + 8 != path.stat().st_size):
                        return False, "wave_length_mismatch"
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
                if sample.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
                    return False, "invalid_text_encoding"
                if sample.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
                    return _validate_utf16_text(stream, sample)
            if not sample or b"\x00" in sample:
                return False, "invalid_text"
            for encoding in ("utf-8-sig", "gb18030", "big5", "shift_jis"):
                try:
                    sample.decode(encoding)
                    return True, "valid_text"
                except UnicodeDecodeError:
                    continue
            # Windows Japanese files can contain vendor extensions to Shift-JIS.
            try:
                decoded = sample.decode("cp932")
            except UnicodeDecodeError:
                return False, "invalid_text_encoding"
            if any((ord(char) < 32 and char not in "\t\r\n")
                   or 127 <= ord(char) <= 159 for char in decoded):
                return False, "invalid_text"
            return True, "valid_text"
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        return False, "image_pixel_limit"
    except (OSError, ValueError, TypeError, mutagen.MutagenError):
        return False, "validation_failed"

    return False, "unsupported_format"
