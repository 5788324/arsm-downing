from __future__ import annotations

import base64
from pathlib import Path

import pytest
from mutagen.id3 import APIC, ID3, TIT2, USLT

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


def test_write_id3_embeds_simplified_lrc_and_cover(tmp_path: Path) -> None:
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"\xff\xd8\xffimage")
    lyrics = tmp_path / "track.lrc"
    lyrics.write_text("[00:01.00]繁體聲音與後臺", encoding="utf-8")
    tags = ID3()

    AudioProcessor._write_id3(
        tags, tmp_path / "track.mp3", metadata(), cover, lyrics)

    assert tags.getall("APIC")
    embedded = tags.getall("USLT")
    assert len(embedded) == 1
    assert embedded[0].text == "[00:01.00]繁体声音与后台"


def test_write_id3_preserves_existing_lyrics_without_sidecar(tmp_path: Path) -> None:
    tags = ID3()
    tags.add(USLT(encoding=3, lang="zho", desc="existing", text="原歌词"))

    AudioProcessor._write_id3(tags, tmp_path / "track.mp3", metadata(), None)

    assert tags.getall("USLT")[0].text == "原歌词"



def test_write_id3_preserves_existing_cover_without_new_cover(tmp_path: Path) -> None:
    tags = ID3()
    tags.add(APIC(encoding=3, mime="image/jpeg", type=3, data=b"old-cover"))

    AudioProcessor._write_id3(tags, tmp_path / "track.mp3", metadata(), None)

    assert tags.getall("APIC")[0].data == b"old-cover"


def test_sync_id3_assets_preserves_metadata_and_is_idempotent(tmp_path: Path) -> None:
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"\xff\xd8\xffnew-cover")
    lyrics = tmp_path / "track.lrc"
    lyrics.write_text("[00:01.00]繁體", encoding="utf-8")
    tags = ID3()
    tags.add(TIT2(encoding=3, text=["原始标题"]))

    assert AudioProcessor._sync_id3_assets(tags, cover, lyrics) is True
    assert tags.getall("TIT2")[0].text == ["原始标题"]
    assert tags.getall("USLT")[0].text == "[00:01.00]繁体"
    assert AudioProcessor._sync_id3_assets(tags, cover, lyrics) is False

def test_matching_lyrics_prefers_nearest_same_locale(tmp_path: Path) -> None:
    audio = tmp_path / "CN" / "MP3" / "01 标题.mp3"
    cn = tmp_path / "CN" / "LRC" / "01 标题.lrc"
    tw = tmp_path / "TW" / "LRC" / "01 标题.lrc"
    cn.parent.mkdir(parents=True)
    tw.parent.mkdir(parents=True)
    cn.write_text("简体", encoding="utf-8")
    tw.write_text("繁體", encoding="utf-8")

    assert AudioProcessor.find_matching_lyrics(audio, [tw, cn]) == cn


def test_canonical_lyrics_path_removes_audio_suffix() -> None:
    source = Path("第1章 『宫殿』 4人章 【序幕 音轨】.wav.vtt")
    assert AudioProcessor.canonical_lyrics_path(source) == Path(
        "第1章 『宫殿』 4人章 【序幕 音轨】.lrc")


def test_prepare_vtt_creates_simplified_canonical_lrc(tmp_path: Path) -> None:
    source = tmp_path / "第1章.wav.vtt"
    source.write_text(
        "WEBVTT\n\n00:00:01.230 --> 00:00:03.000\n"
        "<v Narrator>繁體聲音&amp;後臺</v>\n\n"
        "01:02:03.450 --> 01:02:05.000\n第二行\n",
        encoding="utf-8",
    )

    result = AudioProcessor.prepare_lyrics_sidecar(source)

    assert result == tmp_path / "第1章.lrc"
    assert result.read_text(encoding="utf-8") == (
        "[00:01.23]繁体声音&后台\n[62:03.45]第二行\n"
    )
    assert source.is_file()


def test_canonical_lrc_is_not_rewritten(tmp_path: Path) -> None:
    source = tmp_path / "track.lrc"
    source.write_text("繁體", encoding="utf-8")
    assert AudioProcessor.prepare_lyrics_sidecar(source) == source
    assert source.read_text(encoding="utf-8") == "繁體"


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

def test_postprocess_tags_each_completed_audio_once(
    tmp_path: Path, monkeypatch
) -> None:
    from types import SimpleNamespace

    from core.models import TrackItem
    from core.orchestrator import Orchestrator

    audio = tmp_path / "track.mp3"
    lyric = tmp_path / "track.lrc"
    audio.write_bytes(b"audio")
    lyric.write_text("[00:00.00]歌词", encoding="utf-8")
    audio_target = TrackItem(
        id="audio", title=audio.name, type="audio", url="",
        size=audio.stat().st_size, save_path=audio,
    )
    lyric_target = TrackItem(
        id="lyric", title=lyric.name, type="text", url="",
        size=lyric.stat().st_size, save_path=lyric,
    )
    calls = []
    monkeypatch.setattr(
        AudioProcessor, "apply_tags",
        staticmethod(lambda path, meta, cover, lyrics:
                     calls.append((path, lyrics)) or True),
    )

    orchestrator = Orchestrator.__new__(Orchestrator)
    orchestrator.config = SimpleNamespace(tag_audio=True)
    tagged = orchestrator._postprocess_completed_work(
        metadata(), None, tmp_path,
    )

    assert calls == [(audio, lyric)]
    assert tagged == [(audio, audio.stat().st_size)]


def test_embedded_cover_recognizes_non_mp3_media(tmp_path: Path, monkeypatch) -> None:
    media = tmp_path / "track.wav"
    media.write_bytes(b"RIFF-not-real")
    fake = type("Tagged", (), {"pictures": [], "tags": {"APIC:Cover": object()}})()
    monkeypatch.setattr("core.audio.mutagen.File", lambda _path: fake)
    assert AudioProcessor.has_embedded_cover(media) is True


def test_embedded_cover_rejects_non_media(tmp_path: Path) -> None:
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"image")
    assert AudioProcessor.has_embedded_cover(cover) is False


def test_postprocess_uses_explicit_targets_when_long_tree_scan_misses_files(
    tmp_path: Path, monkeypatch
) -> None:
    from types import SimpleNamespace

    from core.orchestrator import Orchestrator

    nested = tmp_path / "nested"
    nested.mkdir()
    audio = nested / "track.mp3"
    subtitle = nested / "track.mp3.vtt"
    audio.write_bytes(b"audio")
    subtitle.write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n繁體歌詞\n",
        encoding="utf-8",
    )
    calls = []
    monkeypatch.setattr(
        AudioProcessor, "apply_tags",
        staticmethod(lambda path, meta, cover, lyrics:
                     calls.append((path, lyrics)) or True),
    )

    orchestrator = Orchestrator.__new__(Orchestrator)
    orchestrator.config = SimpleNamespace(tag_audio=True)
    tagged = orchestrator._postprocess_completed_work(
        metadata(), None, tmp_path / "unscannable-root", [audio, subtitle])

    expected_lrc = nested / "track.lrc"
    assert expected_lrc.read_text(encoding="utf-8") == "[00:01.00]繁体歌词\n"
    assert subtitle.is_file()
    assert calls == [(audio, expected_lrc)]
    assert tagged == [(audio, audio.stat().st_size)]

def test_decode_text_salvages_nearly_valid_utf8_vtt() -> None:
    payload = (
        b"WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n"
        + "繁體字幕".encode("utf-8")
        + b"\x99\n"
    )

    decoded = AudioProcessor._decode_text(payload)
    converted = AudioProcessor.vtt_to_lrc_text(decoded)

    assert "-->" in decoded
    assert converted == "[00:01.00]繁体字幕�"


def test_sync_mp3_assets_accepts_wave_content_with_mp3_suffix(
    tmp_path: Path, monkeypatch
) -> None:
    disguised_wave = tmp_path / "track.mp3"
    disguised_wave.write_bytes(b"RIFF\x00\x00\x00\x00WAVEdata")
    monkeypatch.setattr(
        "core.audio.MP3",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("must not parse WAV as MPEG")
        ),
    )

    assert AudioProcessor.sync_mp3_assets(disguised_wave, None, None) is False
