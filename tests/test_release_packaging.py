from __future__ import annotations

from pathlib import Path

import pytest

from core.version import APP_VERSION, display_title

pytestmark = pytest.mark.portable
ROOT = Path(__file__).resolve().parents[1]


def test_release_version_is_visible() -> None:
    assert APP_VERSION == "1.0.1"
    assert APP_VERSION in display_title()


def test_pyinstaller_spec_has_no_user_specific_path() -> None:
    content = (ROOT / "ARSMSuite.spec").read_text(encoding="utf-8")
    assert "C:\\Users" not in content
    assert "ARSM-Suite" in content
    assert "config.example.json" in content
    assert "COLLECT(" in content


def test_release_workflow_and_build_inputs_exist() -> None:
    assert (ROOT / "requirements-build.txt").is_file()
    assert (ROOT / "scripts" / "build_windows.ps1").is_file()
    assert (ROOT / "scripts" / "build_installer.ps1").is_file()
    assert (ROOT / ".github" / "workflows" / "release-build.yml").is_file()
    assert (ROOT / "packaging" / "windows_version_info.txt").is_file()
    assert (ROOT / "packaging" / "ARSM-Suite.iss").is_file()


def test_installer_uses_stable_app_id_and_preserves_user_data() -> None:
    content = (ROOT / "packaging" / "ARSM-Suite.iss").read_text(encoding="utf-8")
    assert "AppId={{B86B4F4B-0E88-4A50-8C73-E2E0C62B5E10}" in content
    assert "{localappdata}\\ARSM Suite" not in content
    assert "UninstallDisplayName=ARSM Suite" in content
    assert "CloseApplications=force" in content