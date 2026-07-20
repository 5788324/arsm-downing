from pathlib import Path

import pytest

from scripts.intake_sandbox_acceptance import run_acceptance


def test_takeover_t6_disposable_acceptance(tmp_path: Path):
    report = run_acceptance(tmp_path / "acceptance")
    assert report["passed"] is True
    assert all(report["checks"].values())
    assert Path(report["report_path"]).exists()
    assert report["second_classification"] == "already_normalized"
    assert report["database_failure"]["state"] == "rolled_back"
    assert report["cleanup_failure"]["recovered_state"] == "completed"


def test_takeover_t6_refuses_unmarked_existing_directory(tmp_path: Path):
    existing = tmp_path / "existing"
    existing.mkdir()
    sentinel = existing / "do-not-delete.txt"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unmarked"):
        run_acceptance(existing)
    assert sentinel.read_text(encoding="utf-8") == "keep"
