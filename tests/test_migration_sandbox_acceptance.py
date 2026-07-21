from pathlib import Path

import pytest

from scripts.migration_sandbox_acceptance import run_acceptance


def test_migration_sandbox_acceptance_passes(tmp_path: Path):
    report = run_acceptance(tmp_path / "migration-sandbox")
    assert report["passed"] is True
    assert all(report["checks"].values())
    assert Path(report["report_path"]).is_file()


def test_migration_sandbox_refuses_unmarked_existing_directory(tmp_path: Path):
    sandbox = tmp_path / "existing"
    sandbox.mkdir()
    sentinel = sandbox / "do-not-delete.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unmarked"):
        run_acceptance(sandbox)
    assert sentinel.read_text(encoding="utf-8") == "preserve"
