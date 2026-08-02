from __future__ import annotations

from datetime import datetime, timezone
import ast
from pathlib import Path
import sqlite3

import pytest

from core.settings_validation import (
    normalize_library_paths,
    validate_proxy_uri,
    validate_writable_directory,
)


def test_cancelled_is_persistent_terminal_state():
    from core.status import WorkStatus
    from core.state_policy import WorkStatePolicy
    assert WorkStatus.normalize("cancelled") is WorkStatus.CANCELLED
    assert WorkStatus.normalize("已取消") is WorkStatus.CANCELLED
    assert WorkStatus.CANCELLED.is_terminal
    assert not WorkStatus.CANCELLED.is_resumable
    assert "cancelled" in WorkStatePolicy.TERMINAL
    assert WorkStatePolicy.decide("queued", "cancelled").allowed
    assert WorkStatePolicy.decide("cancelled", "queued").allowed


@pytest.mark.parametrize("value", [
    "http://127.0.0.1:7897",
    "https://proxy.example:443",
    "http://user:pass@127.0.0.1:8080",
])
def test_proxy_validation_accepts_supported_uris(value):
    assert validate_proxy_uri(value) == value


@pytest.mark.parametrize("value", [
    "socks5://127.0.0.1:7897",
    "127.0.0.1:7897",
    "http://127.0.0.1:99999",
    "http://127.0.0.1:7897/path",
    "http://127.0.0.1:7897?q=1",
])
def test_proxy_validation_rejects_ambiguous_or_unsupported_values(value):
    with pytest.raises(ValueError):
        validate_proxy_uri(value)


def test_writable_output_directory_probe_is_cleaned(tmp_path):
    target = tmp_path / "downloads"
    assert validate_writable_directory(target) == target.resolve()
    assert target.is_dir()
    assert not list(target.glob(".arsm-write-test-*"))


def test_library_paths_are_normalized_and_deduplicated(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    values = normalize_library_paths([root, str(root), ""])
    assert values == [str(root.resolve())]


def test_library_path_rejects_regular_file(tmp_path):
    file_path = tmp_path / "not-a-directory"
    file_path.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        normalize_library_paths([file_path])



def _make_maintenance_db(path: Path, *, status: str = "cancelled") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE downloads ("
            "id TEXT PRIMARY KEY, rj_id TEXT, track_title TEXT, local_path TEXT, "
            "status TEXT, downloaded_bytes INTEGER, total_bytes INTEGER, error TEXT)"
        )
        conn.execute(
            "CREATE TABLE metadata_cache ("
            "rj_id TEXT PRIMARY KEY, fetched_at TEXT, updated_at TEXT)"
        )
        conn.execute(
            "INSERT INTO downloads VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("dl-1", "RJ00000001", "track.mp3", "track.mp3", status, 5, 10, None),
        )
        conn.execute(
            "INSERT INTO metadata_cache VALUES (?, ?, ?)",
            ("RJ00000001", "2020-01-01T00:00:00", "2020-01-01T00:00:00"),
        )
        conn.commit()
    return path


def test_cancelled_is_terminal_for_maintenance_but_protects_retry_metadata(tmp_path):
    from core.tools_maintenance import (
        ACTIVE_STATUSES,
        METADATA_PROTECTED_STATUSES,
        TERMINAL_QUEUE_STATUSES,
        cleanup_metadata_cache,
        preview_metadata_cache_cleanup,
        preview_queue_cleanup,
        preview_vacuum,
        vacuum_database,
    )

    db_path = _make_maintenance_db(tmp_path / "maintenance" / "history.db")
    queue_path = tmp_path / "maintenance" / "queue.json"
    queue_path.write_text(
        '{"RJ00000001": {"status": "Cancelled"}}', encoding="utf-8"
    )

    assert "cancelled" not in ACTIVE_STATUSES
    assert "cancelled" in METADATA_PROTECTED_STATUSES
    assert "cancelled" in TERMINAL_QUEUE_STATUSES

    vacuum = preview_vacuum(db_path)
    assert vacuum["blocked"] is False
    assert vacuum["active_download_rows"] == 0
    assert vacuum_database(db_path)["success"] is True

    queue = preview_queue_cleanup(db_path, queue_path)
    assert queue.blocked is False
    assert queue.active_download_rows == 0
    assert queue.terminal_db_rows == 1
    assert queue.terminal_queue_items == 1

    cache = preview_metadata_cache_cleanup(
        db_path,
        ttl_hours=1,
        now=datetime(2026, 8, 2, tzinfo=timezone.utc),
    )
    assert cache.active_download_rows == 0
    assert cache.expired_rows == 1
    assert cache.protected_expired_rows == 1
    assert cache.removable_rows == 0
    assert cache.candidate_rj_ids == ()
    cleanup = cleanup_metadata_cache(
        db_path,
        preview_token=cache.preview_token,
        ttl_hours=1,
        now=datetime(2026, 8, 2, tzinfo=timezone.utc),
    )
    assert cleanup["success"] is True
    assert cleanup["deleted_rows"] == 0

    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT status FROM downloads WHERE rj_id=?", ("RJ00000001",)
        ).fetchone()[0] == "cancelled"
        assert conn.execute(
            "SELECT COUNT(*) FROM metadata_cache WHERE rj_id=?", ("RJ00000001",)
        ).fetchone()[0] == 1

def test_source_contracts_for_release_blockers():
    root = Path(__file__).resolve().parents[1]
    status = (root / "core" / "status.py").read_text(encoding="utf-8")
    config = (root / "core" / "config.py").read_text(encoding="utf-8")
    network = (root / "core" / "network.py").read_text(encoding="utf-8")
    state_policy = (root / "core" / "state_policy.py").read_text(encoding="utf-8")
    maintenance = (root / "core" / "tools_maintenance.py").read_text(encoding="utf-8")
    orchestrator = (root / "core" / "orchestrator.py").read_text(encoding="utf-8")
    library = (root / "ui" / "views" / "library_view.py").read_text(encoding="utf-8")
    download_base = (root / "ui" / "views" / "download_view_base.py").read_text(encoding="utf-8")
    tools = (root / "ui" / "views" / "tools_view.py").read_text(encoding="utf-8")

    assert 'CANCELLED = "cancelled"' in status
    assert "cover_fallback_to_direct" in config
    assert "direct: bool = False" in network
    assert '"cancelled"' in state_policy
    assert '"cancelled"' in maintenance
    assert "async def retry_cancelled_job" in orchestrator
    assert "resumed_partial" in orchestrator
    assert "final_status = (" in orchestrator and "'cancelled'" in orchestrator
    assert "trying direct" not in orchestrator
    library_tree = ast.parse(library, filename="ui/views/library_view.py")
    library_class = next(
        node for node in library_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "LibraryView"
    )
    anomaly_method = next(
        node for node in library_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "_apply_anomalies"
    )

    def attribute_path(node):
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parent = attribute_path(node.value)
            return f"{parent}.{node.attr}" if parent else node.attr
        return None

    page_info_assignments = [
        node for node in ast.walk(anomaly_method)
        if isinstance(node, ast.Assign)
        and any(attribute_path(target) == "self.page_info.value" for target in node.targets)
    ]
    assert len(page_info_assignments) == 1
    page_info_names = {
        node.id for node in ast.walk(page_info_assignments[0].value)
        if isinstance(node, ast.Name)
    }
    assert "category_label" not in page_info_names
    assert "sort_label" not in page_info_names

    # The later grouping loop legitimately compares each anomaly category with
    # the last rendered category.  This is unrelated to the removed page-info
    # bug and must remain legal.
    assert any(
        isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Name)
        and node.left.id == "category"
        and len(node.ops) == 1
        and isinstance(node.ops[0], ast.NotEq)
        and len(node.comparators) == 1
        and isinstance(node.comparators[0], ast.Name)
        and node.comparators[0].id == "last_category"
        for node in ast.walk(anomaly_method)
    )
    assert "return cached[\"cover_url\"]" not in download_base
    assert "advanced_mode_enabled" in tools
    assert "真实执行已冻结" in tools
