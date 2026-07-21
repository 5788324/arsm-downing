from __future__ import annotations

import base64
from pathlib import Path

import pytest
from mutagen.id3 import ID3

from core.audio import AudioProcessor
from core.models import WorkMetadata

pytestmark = pytest.mark.portable


def metadata() -> WorkMetadata:
    return WorkMetadata(
        rj_id="RJ00000001",
        title="测试专辑",
        circle="测试社团",
        cv=["CV A", "CV B"],
        tags=[],
        price=0,
        dl_count=0,
        source_url="",
        rating=0,
        release_date="2026-01-01",
        cover_url="",
    )


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (b"\xff\xd8\xff\xe0test", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\nrest", "image/png"),
        (b"GIF89a-rest", "image/gif"),
        (b"RIFF1234WEBPrest", "image/webp"),
        (b"unknown", None),
    ],
)
def test_cover_mime_uses_file_signature(tmp_path: Path, header: bytes, expected: str | None) -> None:
    cover = tmp_path / "cover.bin"
    cover.write_bytes(header)
    assert AudioProcessor.cover_mime(cover) == expected


def test_write_id3_uses_publisher_and_real_cover_mime(tmp_path: Path) -> None:
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"\x89PNG\r\n\x1a\nimage")
    tags = ID3()

    AudioProcessor._write_id3(tags, tmp_path / "track.mp3", metadata(), cover)

    assert tags.getall("TIT2")[0].text == ["track"]
    assert tags.getall("TPE1")[0].text == ["CV A, CV B"]
    assert tags.getall("TALB")[0].text == ["测试专辑"]
    assert tags.getall("TPUB")[0].text == ["测试社团"]
    assert tags.getall("APIC")[0].mime == "image/png"


def test_vorbis_cover_uses_metadata_block_picture(tmp_path: Path) -> None:
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"\xff\xd8\xffimage")
    audio: dict[str, list[str]] = {}

    AudioProcessor._set_vorbis_cover(audio, cover)

    encoded = audio["metadata_block_picture"][0]
    assert base64.b64decode(encoded)


def test_apply_tags_dispatches_supported_extension(tmp_path: Path, monkeypatch) -> None:
    audio = tmp_path / "track.opus"
    audio.write_bytes(b"not-real-audio")
    calls = []
    monkeypatch.setattr(
        AudioProcessor,
        "_tag_opus",
        staticmethod(lambda path, meta, cover: calls.append((path, meta.rj_id, cover))),
    )

    assert AudioProcessor.apply_tags(audio, metadata(), None) is True
    assert calls == [(audio, "RJ00000001", None)]


def test_apply_tags_is_non_blocking_on_format_error(tmp_path: Path, monkeypatch) -> None:
    audio = tmp_path / "track.mp3"
    audio.write_bytes(b"broken")
    monkeypatch.setattr(
        AudioProcessor,
        "_tag_mp3",
        staticmethod(lambda *args: (_ for _ in ()).throw(ValueError("bad tag"))),
    )
    assert AudioProcessor.apply_tags(audio, metadata(), None) is False


def test_apply_tags_skips_unsupported_format(tmp_path: Path) -> None:
    audio = tmp_path / "track.xyz"
    audio.write_bytes(b"data")
    assert AudioProcessor.apply_tags(audio, metadata(), None) is False
