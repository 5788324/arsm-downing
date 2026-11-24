import struct
from pathlib import Path
from types import SimpleNamespace

from core.local_file_validation import validate_completed_local_file
from core.orchestrator import Orchestrator


def test_same_name_variants_match_only_their_own_legacy_download_row(tmp_path):
    orchestrator = Orchestrator.__new__(Orchestrator)
    orchestrator.config = SimpleNamespace(sort_files=False)
    nodes = [
        {
            "type": "folder",
            "title": folder,
            "children": [{
                "id": None,
                "title": "track.wav",
                "size": size,
                "mediaDownloadUrl": f"https://example.test/{folder}/track.wav",
            }],
        }
        for folder, size in [("SE", 80), ("No SE", 60)]
    ]
    folders = orchestrator.parse_hierarchy(nodes, tmp_path, tmp_path)
    first, second = orchestrator.deduplicate_tracks([folder.children[0] for folder in folders])
    old_id = orchestrator._make_dl_id("RJ123456", "None", first.save_path, first.title)
    rows = {old_id: {"local_path": str(first.save_path), "total_bytes": 80}}

    assert first.id != second.id
    assert first.source_key != second.source_key
    assert orchestrator._matching_download_row("RJ123456", first, rows) == (
        old_id, rows[old_id],
    )
    second_id, second_row = orchestrator._matching_download_row("RJ123456", second, rows)
    assert second_id != old_id
    assert second_row == {}


def test_rf64_validates_declared_length_and_rejects_appended_tail(tmp_path):
    pcm = bytes(16)
    format_chunk = struct.pack("<4sIHHIIHH", b"fmt ", 16, 1, 1, 8000, 16000, 2, 16)
    data_chunk = b"data" + struct.pack("<I", 0xffffffff) + pcm
    size = 48 + len(format_chunk) + len(data_chunk)
    head = b"RF64" + struct.pack("<I", 0xffffffff) + b"WAVEds64"
    ds64 = struct.pack("<IQQQI", 28, size - 8, len(pcm), len(pcm) // 2, 0)
    audio = head + ds64 + format_chunk + data_chunk
    path = tmp_path / "track.wav.part"

    path.write_bytes(audio)
    assert validate_completed_local_file(path) == (True, "valid_media")
    path.write_bytes(audio + b"wrong source")
    assert validate_completed_local_file(path) == (False, "wave_length_mismatch")
