from __future__ import annotations

import json
import hashlib
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from core.database import LibraryVault
from core.intake_db import replace_path_prefix


class ExternalIntakeDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "history.db"
        self.vault = LibraryVault(self.db_path)

    def tearDown(self) -> None:
        self.vault.close()
        self.temp_dir.cleanup()

    def _seed_work(
        self,
        rj_id: str,
        work_path: str,
        *,
        download_status: str = "registered",
        library_item_path: str | None = None,
        index_paths: tuple[str, ...] = (),
    ) -> None:
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                """INSERT INTO works
                   (rj_id, title, circle, downloaded_at, size_bytes,
                    local_path, cover_url, status)
                   VALUES (?, ?, 'Circle', CURRENT_TIMESTAMP, 123, ?, '', 'verified')""",
                (rj_id, f"Title {rj_id}", work_path),
            )
            connection.execute(
                """INSERT INTO metadata_cache
                   (rj_id, title, circle, cover_url, metadata_json,
                    tracks_json, fetched_at, updated_at)
                   VALUES (?, ?, 'Circle', '', ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                (
                    rj_id,
                    f"Metadata {rj_id}",
                    json.dumps({"id": rj_id}),
                    json.dumps([{"type": "audio", "title": "track01.mp3"}]),
                ),
            )
            connection.execute(
                """INSERT INTO downloads
                   (id, rj_id, track_title, local_path, status,
                    downloaded_bytes, total_bytes, error, updated_at)
                   VALUES (?, ?, 'track01', ?, ?, 10, 10, '', CURRENT_TIMESTAMP)""",
                (f"{rj_id}:track01", rj_id, f"{work_path}/audio/track01.mp3", download_status),
            )
            item_path = library_item_path if library_item_path is not None else work_path
            connection.execute(
                """INSERT INTO library_items
                   (rj_id, folder_path, folder_name, total_files, total_size,
                    audio_count, has_audio, has_cover, warnings_json, scan_run_id, scanned_at)
                   VALUES (?, ?, ?, 1, 10, 1, 1, 1, '[]', 'test-run', CURRENT_TIMESTAMP)""",
                (rj_id, item_path, Path(item_path).name),
            )
            for path in index_paths or (work_path,):
                connection.execute(
                    """INSERT INTO library_index
                       (rj_id, library_path, work_dir, status, size_bytes, file_count, scanned_at)
                       VALUES (?, ?, ?, 'found', 10, 1, CURRENT_TIMESTAMP)""",
                    (rj_id, str(Path(path).parent), path),
                )
            connection.commit()
        finally:
            connection.close()

    def _fetch_path_state(self, rj_id: str) -> dict:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            return {
                "work": connection.execute(
                    "SELECT local_path FROM works WHERE rj_id=?", (rj_id,)
                ).fetchone()[0],
                "downloads": [
                    row[0]
                    for row in connection.execute(
                        "SELECT local_path FROM downloads WHERE rj_id=? ORDER BY id",
                        (rj_id,),
                    ).fetchall()
                ],
                "library_item": connection.execute(
                    "SELECT folder_path FROM library_items WHERE rj_id=?", (rj_id,)
                ).fetchone()[0],
                "library_index": [
                    row[0]
                    for row in connection.execute(
                        "SELECT work_dir FROM library_index WHERE rj_id=? ORDER BY work_dir",
                        (rj_id,),
                    ).fetchall()
                ],
            }
        finally:
            connection.close()

    def test_clean_database_contains_library_items_schema(self) -> None:
        columns = {
            row[1]
            for row in self.vault.conn.execute("PRAGMA table_info(library_items)").fetchall()
        }
        self.assertTrue(
            {
                "rj_id",
                "folder_path",
                "folder_name",
                "total_files",
                "total_size",
                "audio_count",
                "has_audio",
                "has_cover",
                "warnings_json",
                "scan_run_id",
            }.issubset(columns)
        )

    def test_read_only_open_does_not_create_missing_database(self) -> None:
        missing = Path(self.temp_dir.name) / "missing.db"
        with self.assertRaises(FileNotFoundError):
            LibraryVault.open_read_only(missing)
        self.assertFalse(missing.exists())

    def test_snapshot_returns_all_external_intake_context(self) -> None:
        rj_id = "RJ01010001"
        source = "/library/RJ01010001"
        self._seed_work(rj_id, source)

        snapshot = self.vault.get_external_intake_snapshot(rj_id)

        self.assertEqual(snapshot["work"]["local_path"], source)
        self.assertEqual(snapshot["metadata"]["title"], f"Metadata {rj_id}")
        self.assertEqual(snapshot["metadata"]["tracks"][0]["title"], "track01.mp3")
        self.assertEqual(snapshot["library_items"][0]["folder_path"], source)
        self.assertEqual(snapshot["library_index"][0]["work_dir"], source)
        self.assertEqual(snapshot["pending_downloads"], 0)
        self.assertEqual(len(snapshot["snapshot_token"]), 64)

    def test_path_transaction_updates_all_matching_tables_and_records_images(self) -> None:
        rj_id = "RJ01010002"
        source = "/library/RJ01010002"
        target = "/normalized/RJ01010002"
        self._seed_work(rj_id, source)
        token = self.vault.get_external_intake_snapshot(rj_id)["snapshot_token"]

        result = self.vault.update_external_intake_paths(
            rj_id, source, target, expected_preimage_token=token
        )

        self.assertTrue(result["success"], result)
        self.assertEqual(result["updated_rows"]["works"], 1)
        self.assertEqual(result["updated_rows"]["downloads"], 1)
        self.assertEqual(result["updated_rows"]["library_items"], 1)
        self.assertEqual(result["updated_rows"]["library_index"], 1)
        self.assertEqual(result["preimage"]["work"]["local_path"], source)
        self.assertEqual(result["postimage"]["work"]["local_path"], target)
        self.assertNotEqual(result["preimage_token"], result["postimage_token"])

        state = self._fetch_path_state(rj_id)
        self.assertEqual(state["work"], target)
        self.assertEqual(state["library_item"], target)
        self.assertEqual(state["library_index"], [target])
        self.assertEqual(state["downloads"], [f"{target}/audio/track01.mp3"])

    def test_duplicate_source_cannot_replace_primary_record(self) -> None:
        rj_id = "RJ01010003"
        primary = "/library/RJ01010003"
        duplicate = "/intake/RJ01010003 duplicate"
        target = "/quarantine/RJ01010003 duplicate"
        self._seed_work(rj_id, primary, index_paths=(primary, duplicate))
        before = self._fetch_path_state(rj_id)

        result = self.vault.update_external_intake_paths(rj_id, duplicate, target)

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "primary_record_protected")
        self.assertEqual(self._fetch_path_state(rj_id), before)

    def test_download_path_must_be_covered_by_explicit_file_mapping(self) -> None:
        rj_id = "RJ01010014"
        old = "/library/RJ01010014 old"
        new = "/library/RJ01010014"
        self._seed_work(rj_id, old)
        token = self.vault.get_external_intake_snapshot(rj_id)["snapshot_token"]

        result = self.vault.update_external_intake_paths(
            rj_id,
            old,
            new,
            expected_preimage_token=token,
            file_path_mappings={
                f"{old}/cover.jpg": f"{new}/Title/cover.jpg"
            },
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "download_path_not_mapped")
        self.assertEqual(self._fetch_path_state(rj_id)["work"], old)

    def test_file_mapping_must_stay_within_source_and_target_roots(self) -> None:
        rj_id = "RJ01010015"
        old = "/library/RJ01010015 old"
        new = "/library/RJ01010015"
        self._seed_work(rj_id, old)
        token = self.vault.get_external_intake_snapshot(rj_id)["snapshot_token"]

        result = self.vault.update_external_intake_paths(
            rj_id,
            old,
            new,
            expected_preimage_token=token,
            file_path_mappings={
                "/outside/track.mp3": f"{new}/Title/track.mp3"
            },
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "invalid_file_mapping")
        self.assertEqual(self._fetch_path_state(rj_id)["work"], old)

    def test_pending_download_blocks_transaction(self) -> None:
        rj_id = "RJ01010004"
        source = "/library/RJ01010004"
        self._seed_work(rj_id, source, download_status="paused")

        result = self.vault.update_external_intake_paths(
            rj_id, source, "/normalized/RJ01010004"
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "pending_downloads")
        self.assertEqual(self._fetch_path_state(rj_id)["work"], source)

    def test_stale_preimage_token_blocks_transaction(self) -> None:
        rj_id = "RJ01010005"
        source = "/library/RJ01010005"
        self._seed_work(rj_id, source)
        stale_token = self.vault.get_external_intake_snapshot(rj_id)["snapshot_token"]
        self.vault.execute_write(
            "UPDATE metadata_cache SET title=? WHERE rj_id=?",
            ("changed", rj_id),
        )

        result = self.vault.update_external_intake_paths(
            rj_id,
            source,
            "/normalized/RJ01010005",
            expected_preimage_token=stale_token,
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "preimage_changed")
        self.assertEqual(self._fetch_path_state(rj_id)["work"], source)

    def test_target_owned_by_other_rj_is_blocked(self) -> None:
        source_rj = "RJ01010006"
        owner_rj = "RJ01010007"
        source = "/library/RJ01010006"
        occupied = "/library/RJ01010007"
        self._seed_work(source_rj, source)
        self._seed_work(owner_rj, occupied)

        result = self.vault.update_external_intake_paths(source_rj, source, occupied)

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "target_owned_by_other_rj")
        self.assertEqual(self._fetch_path_state(source_rj)["work"], source)

    def test_sqlite_failure_rolls_back_every_table(self) -> None:
        rj_id = "RJ01010008"
        source = "/library/RJ01010008"
        target = "/normalized/RJ01010008"
        self._seed_work(rj_id, source)
        before = self._fetch_path_state(rj_id)
        self.vault.execute_write(
            """CREATE TRIGGER reject_library_item_path_update
               BEFORE UPDATE OF folder_path ON library_items
               BEGIN SELECT RAISE(ABORT, 'injected failure'); END"""
        )

        result = self.vault.update_external_intake_paths(rj_id, source, target)

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "sqlite_error")
        self.assertIn("injected failure", result["error"])
        self.assertEqual(self._fetch_path_state(rj_id), before)

    def test_read_only_vault_rejects_writes(self) -> None:
        rj_id = "RJ01010009"
        source = "/library/RJ01010009"
        self._seed_work(rj_id, source)

        with LibraryVault.open_read_only(self.db_path) as read_only:
            result = read_only.update_external_intake_paths(
                rj_id, source, "/normalized/RJ01010009"
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "read_only_vault")
        self.assertEqual(self._fetch_path_state(rj_id)["work"], source)


    def test_missing_legacy_index_is_created_after_primary_path_update(self) -> None:
        rj_id = "RJ01010010"
        source = "/library/RJ01010010"
        target = "/normalized/RJ01010010"
        self._seed_work(rj_id, source, index_paths=())
        self.vault.execute_write("DELETE FROM library_index WHERE rj_id=?", (rj_id,))

        result = self.vault.update_external_intake_paths(rj_id, source, target)

        self.assertTrue(result["success"], result)
        self.assertEqual(result["updated_rows"]["library_index"], 1)
        self.assertEqual(self._fetch_path_state(rj_id)["library_index"], [target])

    def test_same_rj_source_and_target_index_rows_are_not_auto_deleted(self) -> None:
        rj_id = "RJ01010011"
        source = "/library/RJ01010011"
        target = "/normalized/RJ01010011"
        self._seed_work(rj_id, source, index_paths=(source, target))
        before = self._fetch_path_state(rj_id)

        result = self.vault.update_external_intake_paths(rj_id, source, target)

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "target_reference_conflict")
        self.assertEqual(self._fetch_path_state(rj_id), before)

    def test_library_item_third_path_requires_reconciliation(self) -> None:
        rj_id = "RJ01010012"
        source = "/library/RJ01010012"
        target = "/normalized/RJ01010012"
        self._seed_work(
            rj_id,
            source,
            library_item_path="/other/RJ01010012",
            index_paths=(source,),
        )

        result = self.vault.update_external_intake_paths(rj_id, source, target)

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "library_item_path_mismatch")
        self.assertEqual(self._fetch_path_state(rj_id)["work"], source)

    def test_sqlite_failure_result_keeps_preimage_for_audit(self) -> None:
        rj_id = "RJ01010013"
        source = "/library/RJ01010013"
        self._seed_work(rj_id, source)
        self.vault.execute_write(
            """CREATE TRIGGER reject_library_item_path_update_audit
               BEFORE UPDATE OF folder_path ON library_items
               BEGIN SELECT RAISE(ABORT, 'audit failure'); END"""
        )

        result = self.vault.update_external_intake_paths(
            rj_id, source, "/normalized/RJ01010013"
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["preimage"]["work"]["local_path"], source)
        self.assertEqual(len(result["preimage_token"]), 64)
        self.assertEqual(result["postimage"], {})

    def test_path_prefix_mapping_is_component_safe(self) -> None:
        self.assertEqual(
            replace_path_prefix(
                r"E:\\arsm\\RJ01010010\\disc\\track.mp3",
                r"E:\\arsm\\RJ01010010",
                r"D:\\library\\RJ01010010",
            ),
            r"D:\library\RJ01010010\disc\track.mp3",
        )
        self.assertIsNone(
            replace_path_prefix(
                "/library/RJ010100100/track.mp3",
                "/library/RJ01010010",
                "/target/RJ01010010",
            )
        )


    def test_cli_filelist_verification_uses_read_only_vault(self) -> None:
        rj_id = "RJ01010014"
        root = Path(self.temp_dir.name) / "intake"
        work = root / rj_id / "Title"
        work.mkdir(parents=True)
        (work / "track01.mp3").write_bytes(b"audio")
        self._seed_work(rj_id, str(root / rj_id))
        self.vault.close()
        before = hashlib.sha256(self.db_path.read_bytes()).hexdigest()

        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parents[1] / "tools" / "external_intake.py"),
                "--root",
                str(root),
                "--quarantine-root",
                str(Path(self.temp_dir.name) / "quarantine"),
                "--verify-filelist",
                "--db-path",
                str(self.db_path),
                "--report-root",
                str(Path(self.temp_dir.name) / "reports"),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        after = hashlib.sha256(self.db_path.read_bytes()).hexdigest()
        self.vault = LibraryVault(self.db_path)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("File-list verify: 0 mismatches", result.stdout)
        self.assertEqual(before, after)

    def test_external_intake_tool_contains_no_business_sqlite_connection(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "tools" / "external_intake.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("sqlite3.connect", source)
        self.assertNotIn("UPDATE works", source)
        self.assertNotIn("DELETE FROM works", source)
        self.assertIn("LibraryVault.open_read_only", source)
        tools_view_source = (
            Path(__file__).resolve().parents[1] / "ui" / "views" / "tools_view.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("LibraryVault(", tools_view_source)


if __name__ == "__main__":
    unittest.main()
