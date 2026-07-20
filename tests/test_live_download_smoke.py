from pathlib import Path

import pytest

from scripts.live_download_smoke import DEFAULT_RJ, build_parser, normalize_rj, validate_sandbox


def test_default_live_smoke_is_small_fixed_sample() -> None:
    args = build_parser().parse_args(["--sandbox", "smoke"])
    assert args.rj == DEFAULT_RJ == "RJ01575399"
    assert args.max_bytes == 64 * 1024 * 1024


def test_normalize_rj_rejects_overlong_input() -> None:
    assert normalize_rj("1575399") == "RJ01575399"
    with pytest.raises(ValueError):
        normalize_rj("123456789")


def test_sandbox_refuses_active_application_files(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    (sandbox / "history.db").write_bytes(b"")
    with pytest.raises(ValueError, match="active application markers"):
        validate_sandbox(sandbox)


def test_sandbox_must_be_empty(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    (sandbox / "unrelated.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="must be empty"):
        validate_sandbox(sandbox)
