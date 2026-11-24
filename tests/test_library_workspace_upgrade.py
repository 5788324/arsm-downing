from pathlib import Path
from zipfile import ZipFile
import wave

from core.database import LibraryVault
from core.library_assets import apply_subtitles, inspect_album_assets, subtitle_candidates
from core.library_rebuild import scan_library_snapshot


def test_rebuild_keeps_records_when_a_configured_root_is_offline(tmp_path):
    online = tmp_path / "online"
    offline = tmp_path / "removable"
    for parent, rid in [(online, "RJ11111111"), (offline, "RJ22222222")]:
        (parent / rid).mkdir(parents=True)
        (parent / rid / "audio.wav").write_bytes(b"audio")
    with LibraryVault(tmp_path / "history.db") as db:
        assert db.rebuild_library([str(online), str(offline)])["found"] == 2
        offline.rename(tmp_path / "unmounted-fixture")
        assert not db.rebuild_library([str(online), str(offline)])["success"]
        assert db.get_library_page(search="RJ22222222")["total"] == 1


def test_media_scan_excludes_subtitle_packs_and_keeps_numeric_work_ids(tmp_path):
    captions = tmp_path / "字幕"
    (captions / "20261022[12345部]字幕包").mkdir(parents=True)
    (captions / "RJ11223344").mkdir()
    (tmp_path / "123456").mkdir()
    (tmp_path / "RJ87654321 album").mkdir()
    snapshot = scan_library_snapshot([tmp_path], exclude_paths=[captions])
    assert {entry.rj_id for entry in snapshot.entries} == {"RJ00123456", "RJ87654321"}


def test_incremental_index_search_favorite_asset_checks_and_collections(tmp_path):
    folder = tmp_path / "RJ12345678"
    folder.mkdir()
    (folder / "Track.wav").write_bytes(b"audio")
    (folder / "Track.vtt").write_text("WEBVTT", encoding="utf-8")
    rid = folder.name
    with LibraryVault(tmp_path / "history.db") as db:
        db.execute_write("INSERT INTO works(rj_id,title,status,local_path) VALUES(?,?,?,?)",
                         (rid, "聲音專輯 — 測試", "completed", str(folder)))
        assert db.index_local_album(rid, folder, [tmp_path])
        assert db.get_library_page(search="声音专辑")["total"] == 1
        assert db.get_library_page(category="missing_lrc")["total"] == 1
        db.set_library_favorite(rid, True)
        db.set_library_last_played(rid)
        db.set_library_collection(rid, "我的合集")
        db.save_library_asset_checks([(rid, str(folder), 1)])
        assert db.get_library_page(category="missing_tags")["total"] == 1
        assert db.get_library_page(category="favorite")["total"] == 1
        assert db.get_library_page(category="recent")["total"] == 1
        assert db.get_library_page(category="collection", collection="我的合集")["total"] == 1
        assert db.get_library_detail(rid)["favorite"]
        assert db.rebuild_library([str(tmp_path)])["success"]
        assert db.get_library_page(category="favorite")["total"] == 1


def test_subtitle_preview_resolves_unique_version_and_never_overwrites(tmp_path):
    root = tmp_path / "RJ12345678"
    archive_dir = tmp_path / "subtitle-packs"
    archive_dir.mkdir()
    for variant in ("SE", "No SE"):
        (root / variant).mkdir(parents=True)
        with wave.open(str(root / variant / "track.wav"), "wb") as target:
            target.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            target.writeframes(bytes(160))
    with ZipFile(archive_dir / "RJ12345678.zip", "w") as archive:
        archive.writestr("SE/track.WAV.vtt",
                         "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n繁體聲音\n")
        archive.writestr("track.lrc", "[00:01.00]版本不明确")
        archive.writestr("../outside.lrc", "[00:01.00]invalid entry")
    root = root.resolve()
    plan = inspect_album_assets(root, root.name, str(archive_dir), include_tags=False)
    assert len(plan.subtitles) == 1
    assert plan.subtitles[0].destination == root / "SE" / "track.lrc"
    assert plan.unmatched == 1
    assert subtitle_candidates(str(archive_dir), set(), root.name) == [root.name]
    with LibraryVault(tmp_path / "history.db") as db:
        db.execute_write("INSERT INTO works(rj_id,title,status,local_path) VALUES(?,?,?,?)",
                         (root.name, "fixture", "completed", str(root)))
        db.index_local_album(root.name, root, [tmp_path])
        assert apply_subtitles(db, root.name, root, plan) == 1
        assert apply_subtitles(db, root.name, root, plan) == 0
    assert (root / "SE" / "track.lrc").read_text(encoding="utf8") == "[00:01.00]繁体声音\n"
    assert not (root / "No SE" / "track.lrc").exists()


def test_backfill_preserves_active_album_and_adds_only_stable_missing_local_cards(tmp_path):
    with LibraryVault(tmp_path / "history.db") as db:
        finished, active = "RJ12345678", "RJ12345679"
        for rid in (finished, active):
            folder = tmp_path / rid
            folder.mkdir()
            (folder / "track.wav").write_bytes(b"audio")
            db.execute_write("INSERT INTO works(rj_id,title,status,local_path) VALUES(?,?,?,?)",
                             (rid, "fixture", "completed", str(folder)))
        db.upsert_download("active-id", active, "track.wav", str(tmp_path / active / "track.wav"),
                           "downloading", 1, 5)
        result = db.backfill_downloaded_library([tmp_path])
        assert result["indexed"] == 1
        assert db.get_library_page(search=finished)["total"] == 1
        assert db.get_library_page(search=active)["total"] == 0
        assert db.get_downloads_by_rj(active)[0]["status"] == "downloading"
