from pathlib import Path

from core.download_response import (
    local_partial_size,
    parse_content_range,
    plan_download_response,
)


def test_parse_content_range() -> None:
    parsed = parse_content_range("bytes 10-19/100")
    assert parsed is not None
    assert (parsed.start, parsed.end, parsed.total, parsed.length) == (10, 19, 100, 10)
    assert parse_content_range("bytes */100") is None
    assert parse_content_range("bytes 20-10/100") is None


def test_416_only_completes_when_local_file_is_exact() -> None:
    complete = plan_download_response(
        status=416, headers={}, requested_offset=100,
        expected_size=100, local_size=100,
    )
    incomplete = plan_download_response(
        status=416, headers={}, requested_offset=20,
        expected_size=100, local_size=20,
    )
    assert complete.action == "complete_local"
    assert incomplete.action == "retry_from_zero"


def test_206_requires_matching_range_and_total() -> None:
    ok = plan_download_response(
        status=206,
        headers={"Content-Range": "bytes 20-99/100", "Content-Length": "80"},
        requested_offset=20,
        expected_size=100,
        local_size=20,
    )
    wrong_start = plan_download_response(
        status=206,
        headers={"Content-Range": "bytes 10-99/100"},
        requested_offset=20,
        expected_size=100,
        local_size=20,
    )
    wrong_total = plan_download_response(
        status=206,
        headers={"Content-Range": "bytes 20-89/90"},
        requested_offset=20,
        expected_size=100,
        local_size=20,
    )
    assert (ok.action, ok.mode, ok.initial_bytes) == ("write", "ab", 20)
    assert wrong_start.action == "retry_from_zero"
    assert wrong_total.action == "retry_from_zero"


def test_200_restarts_from_zero() -> None:
    plan = plan_download_response(
        status=200, headers={}, requested_offset=20,
        expected_size=100, local_size=20,
    )
    assert (plan.action, plan.mode, plan.initial_bytes) == ("write", "wb", 0)


def test_local_partial_size_reads_disk_not_database(tmp_path: Path) -> None:
    final_path = tmp_path / "track.mp3"
    part_path = tmp_path / "track.mp3.part"
    final_path.write_bytes(b"old")
    part_path.write_bytes(b"partial-data")
    assert local_partial_size(final_path, part_path, 100) == len(b"partial-data")


def test_numeric_rj_endpoint_removes_display_padding() -> None:
    from core.orchestrator import Orchestrator
    assert Orchestrator._numeric_rj_id("RJ01575399") == "1575399"
