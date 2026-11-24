import json
import sqlite3

from core.database import LibraryVault
from tools.backfill_metadata import collect_candidate_ids, metadata_is_complete, pending_ids


def complete_metadata(title="Title"):
    return {
        "title": title,
        "circle": {"name": "Circle"},
        "tags": [],
        "vas": [],
        "mainCoverUrl": "https://example.invalid/cover.jpg",
    }


def test_candidate_union_and_incomplete_detection(tmp_path):
    db_path = tmp_path / "history.db"
    vault = LibraryVault(db_path)
    vault.execute_write(
        "INSERT INTO works (rj_id, status) VALUES (?, ?)",
        ("RJ00000001", "completed"),
    )
    vault.upsert_download(
        "d2", "RJ00000002", "track", str(tmp_path / "track.mp3"), "queued"
    )
    vault.set_metadata_cache(
        "RJ00000001", "Complete", "Circle", "", complete_metadata(), []
    )
    vault.close()

    with sqlite3.connect(db_path) as conn:
        assert collect_candidate_ids(conn) == ["RJ00000001", "RJ00000002"]
        todo, total = pending_ids(conn)
    assert total == 2
    assert todo == ["RJ00000002"]
    assert metadata_is_complete(complete_metadata())
    assert not metadata_is_complete({"title": "partial"})


def test_metadata_only_upsert_preserves_tracks_and_download_state(tmp_path):
    db_path = tmp_path / "history.db"
    vault = LibraryVault(db_path)
    rj_id = "RJ00000003"
    vault.execute_write(
        "INSERT INTO works (rj_id, title, status, local_path) VALUES (?, ?, ?, ?)",
        (rj_id, "Old", "downloading", "D:/keep"),
    )
    vault.upsert_download("d3", rj_id, "track", "D:/keep/a.mp3", "queued")
    tracks = [{"title": "keep.mp3", "mediaStreamUrl": "signed"}]
    vault.set_metadata_cache(rj_id, "Old", "Old Circle", "old.jpg", {"title": "Old"}, tracks)

    payload = complete_metadata("New")
    vault.upsert_work_metadata(rj_id, "New", "Circle", "new.jpg", payload)

    cache = vault.get_metadata_cache(rj_id, allow_stale=True)
    work = vault.conn.execute(
        "SELECT title, circle, cover_url, status, local_path FROM works WHERE rj_id=?",
        (rj_id,),
    ).fetchone()
    download = vault.conn.execute(
        "SELECT status, local_path FROM downloads WHERE id='d3'"
    ).fetchone()
    vault.close()

    assert json.loads(cache["tracks_json"]) == tracks
    assert json.loads(cache["metadata_json"])["title"] == "New"
    assert tuple(work) == ("New", "Circle", "new.jpg", "downloading", "D:/keep")
    assert tuple(download) == ("queued", "D:/keep/a.mp3")
