from pathlib import Path

import pytest

from tools.postprocess_library_audio import process_album

pytestmark = pytest.mark.portable


def test_incomplete_album_is_skipped_without_writes(tmp_path: Path) -> None:
    album = tmp_path / "RJ01234567"
    album.mkdir()
    vtt = album / "track.wav.vtt"
    vtt.write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n繁體字幕\n",
        encoding="utf-8",
    )
    (album / "track.wav.part").write_bytes(b"incomplete")

    result = process_album(album, execute=True)

    assert result["incomplete_skipped"] is True
    assert not (album / "track.lrc").exists()


def test_completed_album_creates_canonical_lrc(tmp_path: Path) -> None:
    album = tmp_path / "RJ01234567"
    album.mkdir()
    vtt = album / "track.mp3.vtt"
    vtt.write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n繁體字幕\n",
        encoding="utf-8",
    )

    result = process_album(album, execute=True)

    assert result["incomplete_skipped"] is False
    assert (album / "track.lrc").read_text(encoding="utf-8") == (
        "[00:01.00]繁体字幕\n"
    )
