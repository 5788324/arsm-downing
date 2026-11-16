from datetime import datetime
import json
from pathlib import Path

import pytest

from core.browser_bridge import sanitized_rj_state
from core.database import LibraryVault
from core.services.download_service import DownloadService


def _seed_completed(vault: LibraryVault, root: Path, rj_id: str = "RJ01000001") -> Path:
    album = root / f"{rj_id} Album"
    album.mkdir(parents=True)
    (album / "track.mp3").write_bytes(b"audio")
    (album / "cover.jpg").write_bytes(b"cover")
    vault.execute_write(
        """INSERT INTO works
           (rj_id,title,circle,local_path,size_bytes,status,postprocess_status)
           VALUES (?,?,?,?,?,'completed','completed')""",
        (rj_id, "Album", "Circle", str(album), 5),
    )
    vault.execute_write(
        """INSERT INTO library_items
           (rj_id,folder_path,folder_name,total_files,total_size,audio_count,has_audio)
           VALUES (?,?,?,?,?,?,1)""",
        (rj_id, str(album), album.name, 2, 10, 1),
    )
    vault.execute_write(
        """INSERT INTO library_index
           (rj_id,library_path,work_dir,status,size_bytes,file_count)
           VALUES (?,?,?,'found',5,1)""",
        (rj_id, str(root), str(album)),
    )
    vault.execute_write(
        """INSERT INTO metadata_cache
           (rj_id,title,circle,cover_url,metadata_json,tracks_json,fetched_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            rj_id, "Album", "Circle", "https://example.invalid/cover.jpg",
            json.dumps({
                "tags": [{"name": "治愈"}, {"name": "角色扮演"}],
                "vas": [{"name": "示例声优"}],
                "circle": {"name": "Circle"},
            }, ensure_ascii=False),
            "[]", datetime.now(), datetime.now(),
        ),
    )
    vault.execute_write(
        """INSERT INTO downloads
           (id,rj_id,track_title,local_path,status,downloaded_bytes,total_bytes)
           VALUES (?,?,?,?, 'completed',5,5)""",
        (f"{rj_id}-track", rj_id, "track", str(album / "track.mp3")),
    )
    return album


def test_cloud_archive_record_protects_all_enqueue_paths_and_exports_csv(tmp_path: Path) -> None:
    vault = LibraryVault(tmp_path / "history.db")
    try:
        _seed_completed(vault, tmp_path / "library")

        records = vault.mark_cloud_archives(
            ["RJ01000001"], provider="ExampleDrive",
            remote_path="backup/arsm/RJ01000001", note="用户确认已上传",
        )
        csv_path = vault.export_cloud_archives_csv(tmp_path / "cloud_archives.csv")

        assert records[0]["rj_id"] == "RJ01000001"
        assert "RJ01000001" in csv_path.read_text(encoding="utf-8-sig")
        assert vault.find_in_library("RJ01000001")
        assert vault.get_rj_state_batch(["RJ01000001"])["RJ01000001"]["in_library"] is True
        assert sanitized_rj_state(vault, "RJ01000001")["state"] == "cloud_archive"

        # The independent archive ledger still blocks duplicate batch enqueue
        # if historical work/download rows are compacted later.
        vault.execute_write("DELETE FROM downloads WHERE rj_id='RJ01000001'")
        vault.execute_write("DELETE FROM works WHERE rj_id='RJ01000001'")
        preview = DownloadService(vault).preview_enqueue("RJ01000001")
        assert preview.already_in_library == ("RJ01000001",)
        assert preview.ready == ()
    finally:
        vault.close()


def test_cloud_archive_rejects_active_or_unprocessed_work_atomically(tmp_path: Path) -> None:
    vault = LibraryVault(tmp_path / "history.db")
    try:
        _seed_completed(vault, tmp_path / "library", "RJ01000002")
        vault.execute_write(
            "UPDATE downloads SET status='paused' WHERE rj_id='RJ01000002'"
        )
        with pytest.raises(ValueError, match="仍有未完成"):
            vault.mark_cloud_archives(["RJ01000002"])
        assert vault.list_cloud_archives() == []

        vault.execute_write(
            "UPDATE downloads SET status='completed' WHERE rj_id='RJ01000002'"
        )
        vault.execute_write(
            "UPDATE works SET postprocess_status='pending' WHERE rj_id='RJ01000002'"
        )
        with pytest.raises(ValueError, match="后处理尚未完成"):
            vault.mark_cloud_archives(["RJ01000002"])
        assert vault.list_cloud_archives() == []
    finally:
        vault.close()


def test_rebuild_retains_cloud_only_card_after_local_folder_disappears(tmp_path: Path) -> None:
    root = tmp_path / "library"
    vault = LibraryVault(tmp_path / "history.db")
    try:
        album = _seed_completed(vault, root, "RJ01000003")
        vault.mark_cloud_archives(["RJ01000003"], provider="ExampleDrive")
        archive = vault.list_cloud_archives()[0]
        assert "示例声优" in archive["metadata_json"]
        cached_cover = Path(archive["cover_cache_path"])
        assert cached_cover.is_file()
        (album / "track.mp3").unlink()
        (album / "cover.jpg").unlink()
        album.rmdir()
        vault.execute_write("DELETE FROM metadata_cache WHERE rj_id='RJ01000003'")

        result = vault.rebuild_library([str(root)])
        page = vault.get_library_page(category="cloud_archived")
        detail = vault.get_library_detail("RJ01000003")

        assert result["success"] is True
        assert page["total"] == 1
        assert page["items"][0]["folder_path"] == ""
        assert page["items"][0]["archive_provider"] == "ExampleDrive"
        assert Path(page["items"][0]["archive_cover_path"]).is_file()
        assert detail is not None and detail["archived_at"]
        assert detail["metadata_json"]["vas"][0]["name"] == "示例声优"
        assert detail["metadata_json"]["tags"][0]["name"] == "治愈"
        assert vault.find_in_library("RJ01000003")[0]["status"] == "archived"
    finally:
        vault.close()
