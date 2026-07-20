import json
from pathlib import Path

import pytest

from scripts.windows_acceptance import main, validate_active_db, validate_evidence_dir


def test_acceptance_requires_empty_external_evidence_dir(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "note.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="must be empty"):
        validate_evidence_dir(evidence)


def test_active_database_cannot_be_inside_evidence(tmp_path: Path) -> None:
    evidence = validate_evidence_dir(tmp_path / "evidence")
    active = evidence / "history.db"
    active.write_bytes(b"db")
    with pytest.raises(ValueError, match="must not be inside"):
        validate_active_db(active, evidence)


def test_acceptance_can_generate_empty_non_windows_report(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    code = main([
        "--evidence-dir", str(evidence),
        "--allow-non-windows",
        "--skip-portable",
        "--skip-live",
    ])
    assert code == 0
    report = json.loads((evidence / "windows-acceptance-report.json").read_text(encoding="utf-8"))
    assert report["active_database_was_modified"] is False
    assert report["phases"] == []
