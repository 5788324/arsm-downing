from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import config as config_module
from core.config import ConfigManager
from core.paths import application_dir, resolve_runtime_path

pytestmark = pytest.mark.portable


def test_app_home_override_anchors_relative_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ARSM_APP_HOME", str(tmp_path))
    assert application_dir() == tmp_path.resolve()
    assert resolve_runtime_path("Downloads") == (tmp_path / "Downloads").resolve()


def test_config_save_is_atomic_and_round_trips(tmp_path: Path, monkeypatch) -> None:
    config_file = tmp_path / "config.json"
    example_file = tmp_path / "config.example.json"
    example_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config_module, "CONFIG_FILE", config_file)
    monkeypatch.setattr(config_module, "CONFIG_EXAMPLE_FILE", example_file)

    config = ConfigManager()
    config.output_dir = tmp_path / "Downloads"
    config.library_paths = [str(tmp_path / "Library")]
    config.work_concurrency = 2
    config.save()

    assert not (tmp_path / "config.json.tmp").exists()
    payload = json.loads(config_file.read_text(encoding="utf-8"))
    assert payload["work_concurrency"] == 2
    assert payload["output_dir"] == str(tmp_path / "Downloads")


def test_config_save_preserves_existing_file_on_replace_failure(tmp_path: Path, monkeypatch) -> None:
    config_file = tmp_path / "config.json"
    config_file.write_text('{"old": true}\n', encoding="utf-8")
    monkeypatch.setattr(config_module, "CONFIG_FILE", config_file)
    monkeypatch.setattr(config_module, "CONFIG_EXAMPLE_FILE", tmp_path / "missing.json")
    monkeypatch.setattr(config_module, "_replace_file", lambda *args: (_ for _ in ()).throw(OSError("locked")))

    with pytest.raises(OSError, match="locked"):
        ConfigManager().save()

    assert json.loads(config_file.read_text(encoding="utf-8")) == {"old": True}
    assert not (tmp_path / "config.json.tmp").exists()


def test_default_config_and_database_paths_are_resolved_at_use_time(
    tmp_path: Path, monkeypatch
) -> None:
    from core import database as database_module

    monkeypatch.setattr(config_module, "CONFIG_FILE", None)
    monkeypatch.setattr(config_module, "CONFIG_EXAMPLE_FILE", None)
    monkeypatch.setattr(database_module, "DB_FILE", None)
    monkeypatch.setenv("ARSM_APP_HOME", str(tmp_path))

    config = ConfigManager()
    config.save()
    assert (tmp_path / "config.json").is_file()

    vault = database_module.LibraryVault()
    try:
        assert Path(vault.db_path) == tmp_path / "history.db"
    finally:
        vault.close()
    assert (tmp_path / "history.db").is_file()
