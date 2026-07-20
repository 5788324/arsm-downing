from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import external_intake as ext


class ExternalIntakeScanTests(unittest.TestCase):
    def test_norm_rj_and_safe_name(self) -> None:
        self.assertEqual(ext.norm_rj("RJ01087430"), "RJ01087430")
        self.assertEqual(ext.norm_rj("【RJ01087430】title"), "RJ01087430")
        self.assertEqual(ext.norm_rj("01087430"), "RJ01087430")
        self.assertEqual(ext.norm_rj("random_folder"), "")
        self.assertEqual(ext.safe_name("test:file<name>"), "testfilename")
        self.assertLessEqual(len(ext.safe_name("a" * 100)), 80)

    def test_classification_uses_only_temporary_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            normalized = root / "RJ01087430"
            (normalized / "Title").mkdir(parents=True)
            self.assertEqual(
                ext._classify_dir(normalized, "RJ01087430")["action"],
                "already_normalized",
            )

            needs_layer = root / "RJ01087431"
            needs_layer.mkdir()
            (needs_layer / "track01.mp3").write_bytes(b"")
            self.assertEqual(
                ext._classify_dir(needs_layer, "RJ01087431")["action"],
                "needs_title_layer",
            )

            rename = root / "RJ01087432 title"
            rename.mkdir()
            (rename / "track01.mp3").write_bytes(b"")
            self.assertEqual(
                ext._classify_dir(rename, "RJ01087432")["action"],
                "needs_rename_top_level",
            )

            part = root / "RJ01087433"
            (part / "nested").mkdir(parents=True)
            (part / "nested" / "file.part").write_bytes(b"")
            self.assertEqual(
                ext._classify_dir(part, "RJ01087433")["reason"],
                "has_part_files",
            )

            empty = root / "RJ01087434"
            empty.mkdir()
            self.assertEqual(
                ext._classify_dir(empty, "RJ01087434")["reason"],
                "empty_directory",
            )

    def test_nested_track_names_are_extracted(self) -> None:
        tracks = [
            {"type": "audio", "title": "track01.mp3"},
            {
                "type": "folder",
                "children": [{"type": "audio", "title": "inner.mp3"}],
            },
        ]
        self.assertEqual(ext._extract_track_names(tracks), ["track01.mp3", "inner.mp3"])

    def test_missing_root_returns_stable_read_only_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "not-created"
            with mock.patch.object(ext, "E_ROOT", missing):
                dirs_info, plan = ext.scan_top_dirs()

        self.assertEqual(dirs_info, [])
        self.assertFalse(plan["root_exists"])
        self.assertEqual(plan["scanned_top_dirs"], 0)
        self.assertEqual(plan["unique_rj"], 0)
        self.assertEqual(plan["already_normalized"], 0)
        self.assertEqual(plan["blockers"], 0)
        self.assertTrue(plan["execution_frozen"])
        self.assertFalse(plan["can_execute"])


if __name__ == "__main__":
    unittest.main()
