from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.database import LibraryVault
from tools import external_intake as ext


EXPECTED_PLAN_KEYS = {
    "root",
    "root_exists",
    "scanned_top_dirs",
    "unique_rj",
    "actions",
    "fatal_blockers",
    "review_required",
    "quarantine_actions",
    "warnings",
    "can_execute",
    "schema_version",
    "generated_at",
    "quarantine_root",
    "execution_frozen",
    "ready_without_freeze",
    "counts",
}
REQUIRED_ACTION_KEYS = {
    "source",
    "source_name",
    "rj_id",
    "classification",
    "reason",
    "target_root",
    "target_content_dir",
    "files_at_root",
    "subdirectories",
    "has_part",
    "has_symlink",
    "is_empty",
    "issues",
    "db_preimage_token",
    "db_primary_path",
    "db_pending_downloads",
    "db_library_item_paths",
    "db_library_index_paths",
}


class ExternalIntakeScanTests(unittest.TestCase):
    def test_norm_rj_and_safe_name(self) -> None:
        self.assertEqual(ext.norm_rj("RJ01087430"), "RJ01087430")
        self.assertEqual(ext.norm_rj("【RJ01087430】title"), "RJ01087430")
        self.assertEqual(ext.norm_rj("01087430"), "RJ01087430")
        self.assertEqual(ext.norm_rj("random_folder"), "")
        self.assertEqual(ext.safe_name("test:file<name>"), "testfilename")
        self.assertEqual(ext.safe_name("CON"), "_CON")
        self.assertEqual(ext.safe_name("title. "), "title")
        self.assertLessEqual(len(ext.safe_name("a" * 100)), 80)

    def test_fixed_schema_and_all_classifications(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "intake"
            quarantine = base / "quarantine"
            root.mkdir()

            (root / "RJ01087430" / "Title").mkdir(parents=True)

            needs_layer = root / "RJ01087431"
            needs_layer.mkdir()
            (needs_layer / "track01.mp3").write_bytes(b"")

            rename = root / "【RJ01087432】 Title"
            rename.mkdir()
            (rename / "track01.mp3").write_bytes(b"")

            part = root / "RJ01087433"
            (part / "nested").mkdir(parents=True)
            (part / "nested" / "file.part").write_bytes(b"")

            (root / "RJ01087434").mkdir()
            (root / "manual folder").mkdir()

            plan = ext.build_external_intake_plan(root, quarantine).to_dict()

        self.assertEqual(set(plan), EXPECTED_PLAN_KEYS)
        self.assertEqual(plan["schema_version"], ext.PLAN_SCHEMA_VERSION)
        self.assertEqual(plan["scanned_top_dirs"], 6)
        self.assertEqual(plan["unique_rj"], 5)
        self.assertEqual(plan["counts"]["already_normalized"], 1)
        self.assertEqual(plan["counts"]["needs_title_layer"], 1)
        self.assertEqual(plan["counts"]["needs_rename_top_level"], 1)
        self.assertEqual(plan["counts"]["quarantine_candidate"], 3)
        self.assertEqual(len(plan["quarantine_actions"]), 3)
        self.assertTrue(all(REQUIRED_ACTION_KEYS == set(action) for action in plan["actions"]))
        self.assertTrue(plan["execution_frozen"])
        self.assertFalse(plan["can_execute"])

    def test_duplicate_rj_marks_every_candidate_for_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "intake"
            root.mkdir()
            for name in ("RJ01090001", "【RJ01090001】 Alternate"):
                directory = root / name
                directory.mkdir()
                (directory / "track.mp3").write_bytes(b"")

            plan = ext.build_external_intake_plan(root, base / "quarantine").to_dict()

        self.assertEqual(plan["counts"]["duplicate_review"], 2)
        self.assertEqual(len(plan["review_required"]), 2)
        self.assertEqual(
            {action["classification"] for action in plan["actions"]},
            {"duplicate_review"},
        )

    def test_existing_target_path_is_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "intake"
            root.mkdir()
            source = root / "【RJ01090002】 Title"
            source.mkdir()
            (source / "track.mp3").write_bytes(b"")
            (root / "RJ01090002").write_text("conflict", encoding="utf-8")

            plan = ext.build_external_intake_plan(root, base / "quarantine").to_dict()

        action = next(action for action in plan["actions"] if action["rj_id"] == "RJ01090002")
        self.assertEqual(action["classification"], "fatal")
        self.assertEqual(action["reason"], "target_root_conflict")
        self.assertEqual(len(plan["fatal_blockers"]), 1)

    def test_missing_or_unsafe_roots_return_stable_schema(self) -> None:
        missing_plan = ext.build_external_intake_plan(None).to_dict()
        self.assertEqual(set(missing_plan), EXPECTED_PLAN_KEYS)
        self.assertEqual(missing_plan["fatal_blockers"][0]["code"], "root_not_configured")

        relative_plan = ext.build_external_intake_plan("relative/path").to_dict()
        self.assertEqual(relative_plan["fatal_blockers"][0]["code"], "root_not_absolute")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "intake"
            root.mkdir()
            unsafe = root / "quarantine"
            plan = ext.build_external_intake_plan(root, unsafe).to_dict()
        self.assertEqual(plan["fatal_blockers"][0]["code"], "unsafe_quarantine_root")
        self.assertEqual(plan["actions"], [])

    def test_complete_report_does_not_truncate_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "intake"
            root.mkdir()
            for index in range(60):
                (root / f"manual-{index:02d}").mkdir()

            plan = ext.build_external_intake_plan(root, base / "quarantine")
            report_dir = ext.write_plan_report(plan, base / "reports")
            payload = json.loads(
                (report_dir / "external_intake_plan.json").read_text(encoding="utf-8")
            )

        self.assertEqual(len(payload["actions"]), 60)
        self.assertEqual(len(payload["quarantine_actions"]), 60)

    def test_symlink_candidates_are_fatal_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "intake"
            root.mkdir()
            target = base / "target"
            target.mkdir()
            link = root / "RJ01090003"
            try:
                link.symlink_to(target, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symbolic links are not available in this environment")

            plan = ext.build_external_intake_plan(root, base / "quarantine").to_dict()

        self.assertEqual(plan["counts"]["fatal"], 1)
        self.assertEqual(plan["actions"][0]["reason"], "source_is_symlink")
        self.assertTrue(plan["actions"][0]["has_symlink"])


    def test_database_context_promotes_primary_path_mismatch_to_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "intake"
            source = root / "RJ01090004"
            (source / "Title").mkdir(parents=True)
            db_path = base / "history.db"
            with LibraryVault(db_path) as vault:
                vault.execute_write(
                    "INSERT INTO works (rj_id, local_path, status) VALUES (?, ?, 'verified')",
                    ("RJ01090004", str(base / "primary" / "RJ01090004")),
                )
                plan = ext.build_external_intake_plan(root, base / "quarantine")
                annotated = ext.annotate_plan_with_database(plan, vault)

        action = annotated["actions"][0]
        self.assertEqual(action["classification"], "duplicate_review")
        self.assertEqual(action["reason"], "db_primary_path_differs")
        self.assertEqual(len(action["db_preimage_token"]), 64)
        self.assertEqual(len(annotated["review_required"]), 1)
        self.assertFalse(annotated["ready_without_freeze"])

    def test_database_context_promotes_pending_downloads_to_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "intake"
            source = root / "RJ01090005"
            (source / "Title").mkdir(parents=True)
            db_path = base / "history.db"
            with LibraryVault(db_path) as vault:
                vault.execute_write(
                    "INSERT INTO works (rj_id, local_path, status) VALUES (?, ?, 'prepared')",
                    ("RJ01090005", str(source)),
                )
                vault.execute_write(
                    """INSERT INTO downloads
                       (id, rj_id, local_path, status)
                       VALUES (?, ?, ?, 'paused')""",
                    ("RJ01090005:t1", "RJ01090005", str(source / "track.mp3")),
                )
                plan = ext.build_external_intake_plan(root, base / "quarantine")
                annotated = ext.annotate_plan_with_database(plan, vault)

        action = annotated["actions"][0]
        self.assertEqual(action["classification"], "fatal")
        self.assertEqual(action["reason"], "db_pending_downloads")
        self.assertEqual(action["db_pending_downloads"], 1)
        self.assertEqual(len(annotated["fatal_blockers"]), 1)

    def test_tools_view_reuses_app_controller_vault_for_db_annotation(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "ui" / "views" / "tools_view.py"
        ).read_text(encoding="utf-8")
        self.assertIn("annotate_plan_with_database", source)
        self.assertIn("self.app_controller.db", source)
        self.assertNotIn("LibraryVault(", source)

    def test_nested_track_names_are_extracted(self) -> None:
        tracks = [
            {"type": "audio", "title": "track01.mp3"},
            {
                "type": "folder",
                "children": [
                    {"type": "folder", "children": [{"type": "audio", "title": "inner.mp3"}]}
                ],
            },
        ]
        self.assertEqual(ext._extract_track_names(tracks), ["track01.mp3", "inner.mp3"])


if __name__ == "__main__":
    unittest.main()
