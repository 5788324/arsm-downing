from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.portable
REPO_ROOT = Path(__file__).resolve().parents[1]


def test_runtime_dependencies_are_exactly_pinned() -> None:
    lines = [
        line.strip()
        for line in (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert lines
    assert all("==" in line for line in lines)


def test_ci_workflow_uses_portable_gate_on_linux_and_windows() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    assert "ubuntu-latest" in workflow
    assert "windows-latest" in workflow
    assert "python -m pytest" in workflow
    assert "python -m compileall" in workflow
    assert "requirements-dev.txt" in workflow


def test_default_gate_has_no_live_state_files() -> None:
    assert not (REPO_ROOT / "history.db").exists()
    assert not (REPO_ROOT / "config.json").exists()
    assert not (REPO_ROOT / "queue.json").exists()


def test_live_network_script_is_not_in_default_test_tree() -> None:
    script = REPO_ROOT / "scripts" / "test_core_download.py"
    assert script.exists()
    assert not script.is_relative_to(REPO_ROOT / "tests")
