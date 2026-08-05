"""P0-D: progress must be disk-consistent and never exceed 100%.

Issue #20: DB rows said "registered" while the local file was missing or
truncated, so ``SUM(downloaded_bytes)`` over-counted and the UI showed >100%.
``verified_download_progress`` derives progress from actual on-disk state.
"""

from __future__ import annotations

from core.progress import ObservedFile, verified_download_progress


def _file(expected: int, final: int | None = None,
          part: int | None = None) -> ObservedFile:
    return ObservedFile(expected_bytes=expected, final_bytes=final,
                        part_bytes=part)


def test_registered_row_but_missing_file_counts_zero() -> None:
    summary = verified_download_progress([
        _file(expected=100, final=None, part=None),  # DB says registered
        _file(expected=100, final=100),
    ])
    assert summary.complete_files == 1
    assert summary.verified_bytes == 100
    assert summary.progress == 0.5


def test_truncated_final_file_counts_only_actual_bytes() -> None:
    summary = verified_download_progress([
        _file(expected=100, final=40),  # truncated on disk
    ])
    assert summary.complete_files == 0
    assert summary.verified_bytes == 40
    assert summary.progress == 0.4


def test_part_counts_only_actual_part_size() -> None:
    summary = verified_download_progress([
        _file(expected=100, part=37),
    ])
    assert summary.verified_bytes == 37
    assert summary.progress == 0.37


def test_part_never_exceeds_expected() -> None:
    summary = verified_download_progress([
        _file(expected=100, part=250),
    ])
    assert summary.verified_bytes == 100
    assert summary.progress == 1.0


def test_oversized_final_file_is_flagged_and_not_trusted() -> None:
    summary = verified_download_progress([
        _file(expected=100, final=512),
        _file(expected=100, final=100),
    ])
    assert summary.overage_files == 1
    assert summary.has_overage
    assert summary.verified_bytes == 100
    assert summary.complete_files == 1
    assert summary.progress == 0.5


def test_complete_work_reaches_exactly_100_percent() -> None:
    summary = verified_download_progress([
        _file(expected=100, final=100),
        _file(expected=200, final=200),
    ])
    assert summary.complete_files == 2
    assert summary.progress == 1.0


def test_progress_never_exceeds_100_percent() -> None:
    worst = verified_download_progress([
        _file(expected=100, part=400),
        _file(expected=100, final=300),
        _file(expected=100, final=100),
    ])
    assert worst.progress <= 1.0
    assert worst.overage_files >= 1


def test_unknown_size_final_file_counts_as_verified() -> None:
    summary = verified_download_progress([
        _file(expected=0, final=1234),
    ])
    assert summary.complete_files == 1
    assert summary.verified_bytes == 1234
    assert summary.progress == 1.0


def test_empty_expectation_list_is_zero() -> None:
    summary = verified_download_progress([])
    assert summary.total_files == 0
    assert summary.progress == 0.0


def test_mixed_states_aggregate_without_overrun() -> None:
    summary = verified_download_progress([
        _file(expected=100, final=100),   # complete
        _file(expected=100, part=50),     # partial .part
        _file(expected=100, final=None),  # missing
        _file(expected=100, final=999),   # overage
    ])
    assert summary.verified_bytes == 150
    assert summary.complete_files == 1
    assert summary.overage_files == 1
    assert summary.progress == 0.375
