from pathlib import Path

from scripts.library_rebuild_sandbox_acceptance import run_acceptance


def test_library_rebuild_sandbox_acceptance(tmp_path: Path) -> None:
    report = run_acceptance(tmp_path / "library-rebuild")
    assert report["passed"] is True
    assert all(report["checks"].values())
    assert Path(report["report_path"]).is_file()
