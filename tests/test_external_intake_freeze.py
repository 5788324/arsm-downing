from __future__ import annotations

import ast
import asyncio
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
            conn = sqlite3.connect(db_path)
            try:
                conn.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
                conn.execute("INSERT INTO sentinel VALUES ('unchanged')")
                conn.commit()
            finally:
                conn.close()

            quarantine = root / "quarantine"
            backup_parent = root / ".local_backups"
            action = {
                "dir": str(source),
                "rj_id": "RJ01000001",
                "action": "quarantine",
            }

            with mock.patch.object(ext, "E_ROOT", root / "library"), mock.patch.object(
                ext, "QUARANTINE_BASE", quarantine
            ), mock.patch.object(ext.Path, "cwd", return_value=root):
                old_cwd = Path.cwd()
                os.chdir(root)
                try:
                    with self.assertRaises(ext.ExternalIntakeExecutionDisabled):
                        ext.execute_normalize([action], str(db_path))
                finally:
                    os.chdir(old_cwd)

            self.assertTrue(marker.exists(), "source content must remain untouched")
            self.assertFalse(quarantine.exists(), "quarantine directory must not be created")
            self.assertFalse(backup_parent.exists(), "backup directory must not be created")
            conn = sqlite3.connect(db_path)
            try:
                value = conn.execute("SELECT value FROM sentinel").fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(value, "unchanged")

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
            result = subprocess.run(
                [sys.executable, str(script), "--verify-filelist"],
                cwd=tmp,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("history.db does not exist", result.stderr)
            self.assertFalse((Path(tmp) / "history.db").exists())

    def test_dry_run_cli_is_portable_when_library_root_is_missing(self) -> None:
        script = REPO_ROOT / "tools" / "external_intake.py"
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(script), "--dry-run"],
                cwd=tmp,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Scanned: 0 dirs, 0 unique RJ", result.stdout)
            self.assertIn("Report:", result.stdout)

    def test_scan_is_portable_and_reports_execution_frozen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            normalized = root / "RJ01000002"
            (normalized / "Title").mkdir(parents=True)

            with mock.patch.object(ext, "E_ROOT", root):
                dirs_info, plan = ext.scan_top_dirs()

            self.assertEqual(len(dirs_info), 1)
            self.assertEqual(plan["already_normalized"], 1)
            self.assertTrue(plan["would_be_executable_without_freeze"])
            self.assertTrue(plan["execution_frozen"])
            self.assertFalse(plan["can_execute"])

    def test_ui_has_no_live_execute_callback(self) -> None:
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
        self.assertIn("执行整理（安全重构中）", source)
        self.assertNotIn("execute_normalize", method_source)
        self.assertNotIn("shutil", method_source)
        self.assertNotIn("sqlite3", method_source)


if __name__ == "__main__":
    unittest.main()
