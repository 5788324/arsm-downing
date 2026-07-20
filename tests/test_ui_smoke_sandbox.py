from pathlib import Path

import pytest

from scripts.run_ui_smoke import validate_sandbox


def test_ui_smoke_requires_empty_sandbox(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    (sandbox / "file.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="must be empty"):
        validate_sandbox(sandbox)


def test_ui_smoke_creates_new_sandbox(tmp_path: Path) -> None:
    sandbox = validate_sandbox(tmp_path / "sandbox")
    assert sandbox.is_dir()
    assert not any(sandbox.iterdir())
