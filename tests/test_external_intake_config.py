from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import config as config_module


REPO_ROOT = Path(__file__).resolve().parents[1]


class ExternalIntakeConfigTests(unittest.TestCase):
    def test_config_round_trip_preserves_external_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            missing_example = Path(tmp) / "missing-example.json"
            with mock.patch.object(config_module, "CONFIG_FILE", config_path), mock.patch.object(
                config_module, "CONFIG_EXAMPLE_FILE", missing_example
            ):
                config = config_module.ConfigManager()
                config.external_intake_root = r"E:\arsm"
                config.external_quarantine_root = r"E:\arsm_quarantine_external"
                config.save()
                loaded = config_module.ConfigManager.load()

        self.assertEqual(loaded.external_intake_root, r"E:\arsm")
        self.assertEqual(
            loaded.external_quarantine_root, r"E:\arsm_quarantine_external"
        )

    def test_example_config_exposes_both_paths(self) -> None:
        payload = json.loads(
            (REPO_ROOT / "config.example.json").read_text(encoding="utf-8")
        )
        self.assertIn("external_intake_root", payload)
        self.assertIn("external_quarantine_root", payload)
        self.assertIsNone(payload["external_intake_root"])
        self.assertIsNone(payload["external_quarantine_root"])

    def test_settings_ui_exposes_and_saves_both_paths(self) -> None:
        source = (REPO_ROOT / "ui" / "views" / "settings_view.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("外部资源扫描目录", source)
        self.assertIn("外部资源隔离目录", source)
        self.assertIn("config.external_intake_root =", source)
        self.assertIn("config.external_quarantine_root =", source)


if __name__ == "__main__":
    unittest.main()
