from __future__ import annotations

from pathlib import Path

import pytest

from core.version import APP_VERSION, display_title

pytestmark = pytest.mark.portable
ROOT = Path(__file__).resolve().parents[1]


def test_release_version_is_visible() -> None:
    assert APP_VERSION == "0.9.0-rc.3"
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
    assert (ROOT / ".github" / "workflows" / "release-build.yml").is_file()
    assert (ROOT / "packaging" / "windows_version_info.txt").is_file()
