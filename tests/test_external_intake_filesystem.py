from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.database import LibraryVault
from core.intake_fs import (
    ExternalIntakeSandboxExecutor,
    IntakeFileExecutionRequest,
    SimulatedProcessInterruption,
    build_identity_file_mappings,
    build_source_plan_manifest,
    build_verification_manifest,
    compare_verification_manifests,
    load_journal,
    request_from_plan_action,
)


class FailingVault:
    def update_external_intake_paths(self, *args, **kwargs):
        return {
            "success": False,
            "error_code": "injected_db_failure",
            "error": "injected database failure",
        }


class ExternalIntakeFilesystemTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.sandbox = self.base / "sandbox"
        self.sandbox.mkdir()
        self.journal_dir = self.sandbox / "journals"
        self.db_path = self.sandbox / "history.db"
        self.vault = LibraryVault(self.db_path)

    def tearDown(self) -> None:
        self.vault.close()
        self.temp_dir.cleanup()

    def _source(self, name: str = "RJ01000001 old title") -> Path:
        source = self.sandbox / "incoming" / name
        (source / "audio").mkdir(parents=True)
        (source / "audio" / "track01.mp3").write_bytes(b"audio-data" * 32)
        (source / "cover.jpg").write_bytes(b"cover-data")
        (source / "metadata.json").write_text(
            json.dumps({"title": name}), encoding="utf-8"
        )
        return source

    def _seed(self, rj_id: str, source: Path) -> str:
        self.vault.execute_write(
            """INSERT INTO works
               (rj_id, title, local_path, status, size_bytes)
               VALUES (?, 'Test', ?, 'verified', 100)""",
            (rj_id, str(source)),
        )
        self.vault.execute_write(
            """INSERT INTO downloads
               (id, rj_id, track_title, local_path, status,
                downloaded_bytes, total_bytes)
               VALUES (?, ?, 'track01', ?, 'completed', 10, 10)""",
            (f"{rj_id}:track01", rj_id, str(source / "audio" / "track01.mp3")),
        )
        self.vault.execute_write(
            """INSERT INTO library_items
               (rj_id, folder_path, folder_name, total_files, total_size,
                audio_count, has_audio, has_cover, warnings_json)
               VALUES (?, ?, ?, 3, 100, 1, 1, 1, '[]')""",
            (rj_id, str(source), source.name),
        )
        self.vault.execute_write(
            """INSERT INTO library_index
               (rj_id, library_path, work_dir, status, size_bytes, file_count)
               VALUES (?, ?, ?, 'found', 100, 3)""",
            (rj_id, str(source.parent), str(source)),
        )
        return self.vault.get_external_intake_snapshot(rj_id)["snapshot_token"]

    def _request(self, rj_id: str, source: Path, target: Path, token: str):
        return IntakeFileExecutionRequest(
            rj_id=rj_id,
            source_path=str(source),
            target_path=str(target),
            sandbox_root=str(self.sandbox),
            expected_preimage_token=token,
            expected_source_manifest_token=build_source_plan_manifest(source).token,
        )

    def _db_paths(self, rj_id: str) -> dict[str, list[str] | str]:
        connection = sqlite3.connect(self.db_path)
        try:
            return {
                "work": connection.execute(
                    "SELECT local_path FROM works WHERE rj_id=?", (rj_id,)
                ).fetchone()[0],
                "downloads": [
                    row[0]
                    for row in connection.execute(
                        "SELECT local_path FROM downloads WHERE rj_id=?", (rj_id,)
                    ).fetchall()
                ],
                "items": [
                    row[0]
                    for row in connection.execute(
                        "SELECT folder_path FROM library_items WHERE rj_id=?", (rj_id,)
                    ).fetchall()
                ],
                "index": [
                    row[0]
                    for row in connection.execute(
                        "SELECT work_dir FROM library_index WHERE rj_id=?", (rj_id,)
                    ).fetchall()
                ],
            }
        finally:
            connection.close()

    def test_plan_manifest_and_file_mappings_are_complete(self) -> None:
        source = self._source()
        manifest = build_source_plan_manifest(source)
        mappings = build_identity_file_mappings(source, prefix="Title")

        self.assertEqual(manifest.file_count, 3)
        self.assertEqual(len(mappings), 3)
        self.assertEqual(
            {item["target_relative"] for item in mappings},
            {
                "Title/audio/track01.mp3",
                "Title/cover.jpg",
                "Title/metadata.json",
            },
        )
        self.assertEqual(sum(item["size"] for item in mappings), manifest.total_size)

    def test_verification_detects_relative_path_and_hash_changes(self) -> None:
        source = self._source()
        copied = self.sandbox / "copied"
        import shutil

        shutil.copytree(source, copied)
        expected = build_verification_manifest(source)
        actual = build_verification_manifest(copied)
        self.assertEqual(compare_verification_manifests(expected, actual), (True, ""))

        (copied / "cover.jpg").write_bytes(b"tampered!!")
        actual = build_verification_manifest(copied)
        matches, reason = compare_verification_manifests(expected, actual)
        self.assertFalse(matches)
        self.assertIn("hash mismatch", reason)

    def test_file_mappings_create_title_layer_in_target(self) -> None:
        rj_id = "RJ01000001"
        source = self._source()
        target = self.sandbox / "library" / rj_id
        token = self._seed(rj_id, source)
        mappings = tuple(build_identity_file_mappings(source, prefix="Mapped Title"))
        request = IntakeFileExecutionRequest(
            rj_id=rj_id,
            source_path=str(source),
            target_path=str(target),
            sandbox_root=str(self.sandbox),
            expected_preimage_token=token,
            expected_source_manifest_token=build_source_plan_manifest(source).token,
            file_mappings=mappings,
        )
        journal = ExternalIntakeSandboxExecutor(self.vault, self.journal_dir).execute(request)

        self.assertTrue(journal.success)
        mapped_track = target / "Mapped Title" / "audio" / "track01.mp3"
        self.assertTrue(mapped_track.exists())
        self.assertFalse((target / "audio" / "track01.mp3").exists())
        self.assertEqual(self._db_paths(rj_id)["downloads"], [str(mapped_track.resolve())])

    def test_successful_transaction_moves_files_and_updates_all_path_tables(self) -> None:
        rj_id = "RJ01000001"
        source = self._source()
        target = self.sandbox / "library" / rj_id
        token = self._seed(rj_id, source)
        request = self._request(rj_id, source, target, token)
        executor = ExternalIntakeSandboxExecutor(self.vault, self.journal_dir)

        journal = executor.execute(request)

        self.assertTrue(journal.success)
        self.assertEqual(journal.state, "completed")
        self.assertFalse(source.exists())
        self.assertTrue((target / "audio" / "track01.mp3").exists())
        self.assertFalse(Path(journal.rollback_path).exists())
        paths = self._db_paths(rj_id)
        self.assertEqual(paths["work"], str(target.resolve()))
        self.assertEqual(paths["items"], [str(target.resolve())])
        self.assertEqual(paths["index"], [str(target.resolve())])
        self.assertEqual(paths["downloads"], [str(target.resolve() / "audio" / "track01.mp3")])
        persisted = load_journal(self.journal_dir / f"{request.transaction_id}.json")
        self.assertEqual(persisted.state, "completed")

    def test_database_failure_restores_original_source_and_removes_target(self) -> None:
        source = self._source()
        target = self.sandbox / "library" / "RJ01000001"
        request = IntakeFileExecutionRequest(
            rj_id="RJ01000001",
            source_path=str(source),
            target_path=str(target),
            sandbox_root=str(self.sandbox),
            expected_preimage_token="a" * 64,
            expected_source_manifest_token=build_source_plan_manifest(source).token,
        )
        executor = ExternalIntakeSandboxExecutor(FailingVault(), self.journal_dir)

        journal = executor.execute(request)

        self.assertFalse(journal.success)
        self.assertEqual(journal.state, "rolled_back")
        self.assertEqual(journal.error_code, "injected_db_failure")
        self.assertTrue((source / "cover.jpg").exists())
        self.assertFalse(target.exists())
        self.assertFalse(Path(journal.rollback_path).exists())

    def test_file_failure_after_source_parked_is_rolled_back(self) -> None:
        source = self._source()
        target = self.sandbox / "library" / "RJ01000001"

        def inject(stage, journal):
            if stage == "after_source_parked":
                raise OSError("injected file failure")

        request = IntakeFileExecutionRequest(
            rj_id="RJ01000001",
            source_path=str(source),
            target_path=str(target),
            sandbox_root=str(self.sandbox),
            expected_preimage_token="b" * 64,
            expected_source_manifest_token=build_source_plan_manifest(source).token,
        )
        executor = ExternalIntakeSandboxExecutor(
            FailingVault(), self.journal_dir, fault_injector=inject
        )

        journal = executor.execute(request)

        self.assertEqual(journal.state, "rolled_back")
        self.assertTrue(source.exists())
        self.assertFalse(target.exists())
        self.assertFalse(Path(journal.staging_path).exists())

    def test_rollback_failure_marks_stop_required_and_preserves_backup(self) -> None:
        source = self._source()
        target = self.sandbox / "library" / "RJ01000001"

        def inject(stage, journal):
            if stage == "after_source_parked":
                raise OSError("injected execution failure")

        class BrokenRollbackExecutor(ExternalIntakeSandboxExecutor):
            def _rollback_filesystem(self, journal):
                return False, "injected rollback failure"

        request = IntakeFileExecutionRequest(
            rj_id="RJ01000001",
            source_path=str(source),
            target_path=str(target),
            sandbox_root=str(self.sandbox),
            expected_preimage_token="4" * 64,
            expected_source_manifest_token=build_source_plan_manifest(source).token,
        )
        journal = BrokenRollbackExecutor(
            FailingVault(), self.journal_dir, fault_injector=inject
        ).execute(request)

        self.assertEqual(journal.state, "stop_required")
        self.assertTrue(journal.stop_required)
        self.assertIn("rollback failed", journal.error)
        self.assertFalse(source.exists())
        self.assertTrue(Path(journal.rollback_path).exists())

    def test_target_conflict_fails_before_filesystem_mutation(self) -> None:
        source = self._source()
        target = self.sandbox / "library" / "RJ01000001"
        target.mkdir(parents=True)
        marker = target / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        request = IntakeFileExecutionRequest(
            rj_id="RJ01000001",
            source_path=str(source),
            target_path=str(target),
            sandbox_root=str(self.sandbox),
            expected_preimage_token="c" * 64,
            expected_source_manifest_token=build_source_plan_manifest(source).token,
        )
        executor = ExternalIntakeSandboxExecutor(FailingVault(), self.journal_dir)

        journal = executor.execute(request)

        self.assertEqual(journal.state, "failed")
        self.assertEqual(journal.error_code, "target_exists")
        self.assertTrue(source.exists())
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_source_plan_drift_fails_before_copy(self) -> None:
        source = self._source()
        token = build_source_plan_manifest(source).token
        (source / "new.txt").write_text("changed", encoding="utf-8")
        target = self.sandbox / "library" / "RJ01000001"
        request = IntakeFileExecutionRequest(
            rj_id="RJ01000001",
            source_path=str(source),
            target_path=str(target),
            sandbox_root=str(self.sandbox),
            expected_preimage_token="d" * 64,
            expected_source_manifest_token=token,
        )
        executor = ExternalIntakeSandboxExecutor(FailingVault(), self.journal_dir)

        journal = executor.execute(request)

        self.assertEqual(journal.error_code, "source_plan_changed")
        self.assertTrue(source.exists())
        self.assertFalse(target.exists())

    def test_crash_before_database_update_is_recovered_from_journal(self) -> None:
        source = self._source()
        target = self.sandbox / "library" / "RJ01000001"

        def inject(stage, journal):
            if stage == "after_target_commit":
                raise SimulatedProcessInterruption("simulated process death")

        request = IntakeFileExecutionRequest(
            rj_id="RJ01000001",
            source_path=str(source),
            target_path=str(target),
            sandbox_root=str(self.sandbox),
            expected_preimage_token="e" * 64,
            expected_source_manifest_token=build_source_plan_manifest(source).token,
        )
        executor = ExternalIntakeSandboxExecutor(
            FailingVault(), self.journal_dir, fault_injector=inject
        )
        with self.assertRaises(SimulatedProcessInterruption):
            executor.execute(request)

        journal_path = self.journal_dir / f"{request.transaction_id}.json"
        interrupted = load_journal(journal_path)
        self.assertEqual(interrupted.state, "target_committed")
        self.assertFalse(source.exists())
        self.assertTrue(target.exists())
        self.assertTrue(Path(interrupted.rollback_path).exists())

        recovered = ExternalIntakeSandboxExecutor(
            FailingVault(), self.journal_dir
        ).recover(journal_path)
        self.assertEqual(recovered.state, "rolled_back")
        self.assertTrue(source.exists())
        self.assertFalse(target.exists())

    def test_crash_after_database_update_finishes_committed_transaction(self) -> None:
        rj_id = "RJ01000001"
        source = self._source()
        target = self.sandbox / "library" / rj_id
        token = self._seed(rj_id, source)

        def inject(stage, journal):
            if stage == "after_db_update":
                raise SimulatedProcessInterruption("simulated process death")

        request = self._request(rj_id, source, target, token)
        executor = ExternalIntakeSandboxExecutor(
            self.vault, self.journal_dir, fault_injector=inject
        )
        with self.assertRaises(SimulatedProcessInterruption):
            executor.execute(request)

        journal_path = self.journal_dir / f"{request.transaction_id}.json"
        interrupted = load_journal(journal_path)
        self.assertEqual(interrupted.state, "db_updated")
        self.assertTrue(target.exists())
        self.assertTrue(Path(interrupted.rollback_path).exists())
        self.assertEqual(self._db_paths(rj_id)["work"], str(target.resolve()))

        recovered = ExternalIntakeSandboxExecutor(
            self.vault, self.journal_dir
        ).recover(journal_path)
        self.assertTrue(recovered.success)
        self.assertEqual(recovered.state, "completed")
        self.assertFalse(Path(recovered.rollback_path).exists())
        self.assertTrue(target.exists())

    def test_batch_stops_after_first_failure_and_leaves_later_item_unstarted(self) -> None:
        first_source = self._source("RJ01000001 first")
        second_source = self._source("RJ01000002 second")
        third_source = self._source("RJ01000003 third")
        first_token = self._seed("RJ01000001", first_source)
        second_token = self._seed("RJ01000002", second_source)
        third_token = self._seed("RJ01000003", third_source)
        requests = [
            self._request(
                "RJ01000001", first_source, self.sandbox / "library" / "RJ01000001", first_token
            ),
            self._request(
                "RJ01000002", second_source, self.sandbox / "library" / "RJ01000002", second_token
            ),
            self._request(
                "RJ01000003", third_source, self.sandbox / "library" / "RJ01000003", third_token
            ),
        ]
        (second_source / "drift.txt").write_text("drift", encoding="utf-8")
        executor = ExternalIntakeSandboxExecutor(self.vault, self.journal_dir)

        result = executor.execute_batch(requests)

        self.assertTrue(result.stopped)
        self.assertEqual(result.completed, 1)
        self.assertEqual(result.failed, 1)
        self.assertEqual(len(result.journals), 2)
        self.assertFalse(first_source.exists())
        self.assertTrue(second_source.exists())
        self.assertTrue(third_source.exists())
        self.assertFalse((self.sandbox / "library" / "RJ01000003").exists())

    def test_journal_directory_outside_sandbox_is_rejected_before_write(self) -> None:
        source = self._source()
        request = IntakeFileExecutionRequest(
            rj_id="RJ01000001",
            source_path=str(source),
            target_path=str(self.sandbox / "library" / "RJ01000001"),
            sandbox_root=str(self.sandbox),
            expected_preimage_token="6" * 64,
            expected_source_manifest_token=build_source_plan_manifest(source).token,
        )
        outside_journals = self.base / "outside-journals"
        executor = ExternalIntakeSandboxExecutor(FailingVault(), outside_journals)
        with self.assertRaises(ValueError):
            executor.execute(request)
        self.assertFalse(outside_journals.exists())

    def test_source_tree_symlink_returns_failed_journal_when_supported(self) -> None:
        source = self._source()
        link = source / "linked-cover.jpg"
        try:
            link.symlink_to(source / "cover.jpg")
        except (OSError, NotImplementedError):
            self.skipTest("symbolic links are not available")
        request = IntakeFileExecutionRequest(
            rj_id="RJ01000001",
            source_path=str(source),
            target_path=str(self.sandbox / "library" / "RJ01000001"),
            sandbox_root=str(self.sandbox),
            expected_preimage_token="7" * 64,
            expected_source_manifest_token="8" * 64,
        )
        journal = ExternalIntakeSandboxExecutor(
            FailingVault(), self.journal_dir
        ).execute(request)
        self.assertEqual(journal.error_code, "unsafe_source_tree")
        self.assertTrue(source.exists())

    def test_transaction_id_path_traversal_is_rejected_before_journal_write(self) -> None:
        source = self._source()
        request = IntakeFileExecutionRequest(
            rj_id="RJ01000001",
            source_path=str(source),
            target_path=str(self.sandbox / "library" / "RJ01000001"),
            sandbox_root=str(self.sandbox),
            expected_preimage_token="5" * 64,
            expected_source_manifest_token=build_source_plan_manifest(source).token,
            transaction_id="../../escape",
        )
        executor = ExternalIntakeSandboxExecutor(FailingVault(), self.journal_dir)
        with self.assertRaises(ValueError):
            executor.execute(request)
        self.assertFalse((self.sandbox / "escape.json").exists())
        self.assertFalse((self.base / "escape.json").exists())

    def test_nested_source_and_target_are_rejected(self) -> None:
        source = self._source()
        target = source / "nested-target"
        request = IntakeFileExecutionRequest(
            rj_id="RJ01000001",
            source_path=str(source),
            target_path=str(target),
            sandbox_root=str(self.sandbox),
            expected_preimage_token="1" * 64,
            expected_source_manifest_token=build_source_plan_manifest(source).token,
        )
        journal = ExternalIntakeSandboxExecutor(
            FailingVault(), self.journal_dir
        ).execute(request)
        self.assertEqual(journal.error_code, "nested_paths")
        self.assertTrue(source.exists())

    def test_request_from_plan_action_rejects_review_and_preserves_mappings(self) -> None:
        source = self._source()
        target = self.sandbox / "library" / "RJ01000001"
        action = {
            "classification": "needs_rename_top_level",
            "issues": [],
            "rj_id": "RJ01000001",
            "source": str(source),
            "target_root": str(target),
            "db_preimage_token": "2" * 64,
            "source_manifest_token": build_source_plan_manifest(source).token,
            "file_mappings": build_identity_file_mappings(source, prefix="Title"),
        }
        request = request_from_plan_action(action, sandbox_root=self.sandbox)
        self.assertEqual(len(request.file_mappings), 3)
        action["issues"] = ["manual_review"]
        with self.assertRaises(ValueError):
            request_from_plan_action(action, sandbox_root=self.sandbox)

    def test_recovery_rejects_journal_with_paths_outside_sandbox(self) -> None:
        source = self._source()
        request = IntakeFileExecutionRequest(
            rj_id="RJ01000001",
            source_path=str(source),
            target_path=str(self.sandbox / "library" / "RJ01000001"),
            sandbox_root=str(self.sandbox),
            expected_preimage_token="3" * 64,
            expected_source_manifest_token=build_source_plan_manifest(source).token,
        )
        executor = ExternalIntakeSandboxExecutor(FailingVault(), self.journal_dir)
        journal = executor._new_journal(request)
        journal.target_path = str(self.base / "outside" / "RJ01000001")
        journal_path = self.journal_dir / f"{request.transaction_id}.json"
        journal_path.write_text(json.dumps(journal.to_dict()), encoding="utf-8")

        recovered = executor.recover(journal_path)
        self.assertEqual(recovered.error_code, "unsafe_journal")
        self.assertTrue(recovered.stop_required)
        self.assertTrue(source.exists())

    def test_paths_outside_sandbox_are_rejected(self) -> None:
        source = self._source()
        target = self.base / "outside" / "RJ01000001"
        request = IntakeFileExecutionRequest(
            rj_id="RJ01000001",
            source_path=str(source),
            target_path=str(target),
            sandbox_root=str(self.sandbox),
            expected_preimage_token="f" * 64,
            expected_source_manifest_token=build_source_plan_manifest(source).token,
        )
        journal = ExternalIntakeSandboxExecutor(
            FailingVault(), self.journal_dir
        ).execute(request)
        self.assertEqual(journal.error_code, "outside_sandbox")
        self.assertTrue(source.exists())
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
