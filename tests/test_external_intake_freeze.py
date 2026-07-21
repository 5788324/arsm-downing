from __future__ import annotations

import ast
import asyncio
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools import external_intake as ext


REPO_ROOT = Path(__file__).resolve().parents[1]


class ExternalIntakeFreezeTests(unittest.TestCase):
    def test_execute_normalize_fails_before_any_side_effect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "library" / "RJ01000001"
            source.mkdir(parents=True)
            marker = source / "track01.mp3"
            marker.write_bytes(b"audio")

            db_path = root / "history.db"
            connection = sqlite3.connect(db_path)
            try:
                connection.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
                connection.execute("INSERT INTO sentinel VALUES ('unchanged')")
                connection.commit()
            finally:
                connection.close()

            with self.assertRaises(ext.ExternalIntakeExecutionDisabled):
                ext.execute_normalize(
                    [{"source": str(source), "rj_id": "RJ01000001"}], db_path
                )

            self.assertTrue(marker.exists())
            connection = sqlite3.connect(db_path)
            try:
                value = connection.execute("SELECT value FROM sentinel").fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(value, "unchanged")
            self.assertFalse((root / ".local_backups").exists())

    def test_execute_cli_fails_closed_with_nonzero_exit(self) -> None:
        script = REPO_ROOT / "tools" / "external_intake.py"
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(script), "--execute", "--confirm-bulk"],
                cwd=tmp,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("STOP: external intake mutations are frozen", result.stderr)
            self.assertFalse((Path(tmp) / ".local_backups").exists())
            self.assertFalse((Path(tmp) / "history.db").exists())

    def test_metadata_refresh_is_frozen_before_service_construction(self) -> None:
        with self.assertRaises(ext.ExternalIntakeExecutionDisabled):
            asyncio.run(ext.refresh_metadata(["RJ01000001"], object()))

    def test_refresh_metadata_cli_fails_closed(self) -> None:
        script = REPO_ROOT / "tools" / "external_intake.py"
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(script), "--refresh-metadata"],
                cwd=tmp,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("STOP: external intake mutations are frozen", result.stderr)
            self.assertFalse((Path(tmp) / "history.db").exists())

    def test_verify_cli_does_not_create_missing_database(self) -> None:
        script = REPO_ROOT / "tools" / "external_intake.py"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "intake"
            root.mkdir()
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--root",
                    str(root),
                    "--verify-filelist",
                    "--db-path",
                    str(Path(tmp) / "history.db"),
                ],
                cwd=tmp,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("does not exist", result.stderr)
            self.assertIn("Report:", result.stdout)
            self.assertTrue((Path(tmp) / ".local_backups").exists())
            self.assertFalse((Path(tmp) / "history.db").exists())

    def test_missing_library_root_returns_stable_nonzero_plan(self) -> None:
        script = REPO_ROOT / "tools" / "external_intake.py"
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "not-created"
            result = subprocess.run(
                [sys.executable, str(script), "--root", str(missing)],
                cwd=tmp,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("Scanned: 0 dirs, 0 unique RJ", result.stdout)
            self.assertIn("fatal_blockers: 1", result.stdout)
            self.assertIn("Report:", result.stdout)

    def test_scan_is_portable_and_reports_execution_frozen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "intake"
            quarantine = Path(tmp) / "quarantine"
            normalized = root / "RJ01000002"
            (normalized / "Title").mkdir(parents=True)

            plan = ext.build_external_intake_plan(root, quarantine).to_dict()

            self.assertEqual(len(plan["actions"]), 1)
            self.assertEqual(plan["counts"]["already_normalized"], 1)
            self.assertTrue(plan["ready_without_freeze"])
            self.assertTrue(plan["execution_frozen"])
            self.assertFalse(plan["can_execute"])

    def test_ui_has_no_live_execute_callback_or_hardcoded_e_drive(self) -> None:
        source_path = REPO_ROOT / "ui" / "views" / "tools_view.py"
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        method = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "external_execute"
        )
        method_source = ast.get_source_segment(source, method) or ""

        self.assertIn("disabled=True", source)
        self.assertIn("真实执行已冻结", source)
        self.assertIn("asyncio.to_thread", source)
        self.assertNotIn(r"E:\\arsm", source)
        self.assertNotIn("execute_normalize", method_source)
        self.assertNotIn("shutil", method_source)
        self.assertNotIn("sqlite3", method_source)

    def test_legacy_mutating_body_was_removed(self) -> None:
        source = (REPO_ROOT / "tools" / "external_intake.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        method = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "execute_normalize"
        )
        method_source = ast.get_source_segment(source, method) or ""
        self.assertNotIn("shutil.move", method_source)
        self.assertNotIn("UPDATE works", method_source)
        self.assertNotIn("DELETE FROM", method_source)


if __name__ == "__main__":
    unittest.main()
