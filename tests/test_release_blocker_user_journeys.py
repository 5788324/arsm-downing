from __future__ import annotations

import asyncio
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.config import ConfigManager
from core.database import LibraryVault
from core.models import WorkMetadata
from core.orchestrator import Orchestrator
from core.services.download_service import DownloadService
from core.status import WorkStatus

pytestmark = pytest.mark.portable


class NoNetworkKernel:
    def __init__(self, config):
        self.config = config
        self.calls = []

    async def stream(self, url, headers=None, purpose="download", *, direct=False):
        self.calls.append((url, purpose, direct))
        raise OSError("network disabled in portable test")

    async def shutdown(self):
        return None


class FakeResponse:
    def __init__(self, payload: bytes, content_type: str = "image/jpeg", status: int = 200):
        self._payload = payload
        self.headers = {"Content-Type": content_type}
        self.status = status
        self.closed = False

    async def read(self):
        return self._payload

    def close(self):
        self.closed = True


class CoverKernel(NoNetworkKernel):
    def __init__(self, config, *, fail_proxy=False, payload=b"\xff\xd8\xffdata", content_type="image/jpeg"):
        super().__init__(config)
        self.fail_proxy = fail_proxy
        self.payload = payload
        self.content_type = content_type

    async def stream(self, url, headers=None, purpose="download", *, direct=False):
        self.calls.append((url, purpose, direct))
        if self.fail_proxy and not direct:
            raise OSError("proxy failed")
        return FakeResponse(self.payload, self.content_type)


def make_orchestrator(tmp_path: Path, kernel_cls=NoNetworkKernel):
    tmp_path.mkdir(parents=True, exist_ok=True)
    config = ConfigManager()
    config.output_dir = tmp_path / "Downloads"
    config.library_paths = [str(config.output_dir)]
    config.sort_files = False
    config.cover_fallback_to_direct = False
    db = LibraryVault(tmp_path / "history.db")
    kernel = kernel_cls(config)
    orc = Orchestrator(kernel, config, db)
    return orc, db, config, kernel


def seed_work(orc: Orchestrator, db: LibraryVault, *, rj_id="RJ00000001", size=10, status="failed"):
    meta_raw = {
        "title": "User Journey",
        "circle": {"name": "Test Circle"},
        "vas": [],
        "tags": [],
        "price": 0,
        "dl_count": 0,
        "rate_average_2dp": 0,
        "release_date": "2026-08-02",
        "mainCoverUrl": "https://example.invalid/cover.png",
    }
    tracks_raw = [{
        "id": "track-1",
        "title": "track.mp3",
        "type": "audio",
        "mediaDownloadUrl": "https://example.invalid/track.mp3",
        "size": size,
    }]
    db.set_metadata_cache(
        rj_id=rj_id,
        title=meta_raw["title"],
        circle=meta_raw["circle"]["name"],
        cover_url=meta_raw["mainCoverUrl"],
        metadata_raw=meta_raw,
        tracks_raw=tracks_raw,
    )
    meta = orc._build_metadata(rj_id, meta_raw)
    root = orc.get_save_path(meta)
    root.mkdir(parents=True, exist_ok=True)
    target = orc.parse_hierarchy(tracks_raw, root, root)[0]
    dl_id = orc._make_dl_id(rj_id, target.id or target.title, target.save_path, target.title)
    db.register(meta, 0, root, status="partial" if status != "completed" else "completed")
    db.upsert_download(
        dl_id, rj_id, target.title, str(target.save_path), status,
        0, size,
    )
    return meta, target, dl_id, root


def row_dict(db: LibraryVault, rj_id: str):
    return dict(db.get_downloads_by_rj(rj_id)[0])


def test_status_normalizes_real_ui_cancel_and_metadata_required():
    assert WorkStatus.normalize("Cancelled") is WorkStatus.CANCELLED
    assert WorkStatus.normalize("cancelled") is WorkStatus.CANCELLED
    assert WorkStatus.normalize("已取消") is WorkStatus.CANCELLED
    assert WorkStatus.normalize("Metadata required") is WorkStatus.METADATA_FAILED
    assert WorkStatus.normalize("需要重新获取元数据") is WorkStatus.METADATA_FAILED


def test_failed_partial_resumes_from_largest_local_source(tmp_path):
    orc, db, _config, _kernel = make_orchestrator(tmp_path)
    _meta, target, _dl_id, _root = seed_work(orc, db, size=10)
    target.save_path.write_bytes(b"123456")
    target.save_path.with_suffix(".mp3.part").write_bytes(b"1234")

    result = asyncio.run(orc.resume_job("RJ00000001"))

    assert result["status"] == "queued"
    assert result["resumed_partial"] == 1
    assert row_dict(db, "RJ00000001")["downloaded_bytes"] == 6
    db.close()


def test_complete_part_is_atomically_reconciled_without_network(tmp_path):
    orc, db, _config, _kernel = make_orchestrator(tmp_path)
    _meta, target, _dl_id, _root = seed_work(orc, db, size=10)
    part = target.save_path.with_suffix(".mp3.part")
    part.write_bytes(b"1234567890")

    result = asyncio.run(orc.resume_job("RJ00000001"))

    assert result["status"] == "reconciled_complete"
    assert result["already_complete"] == 1
    assert target.save_path.read_bytes() == b"1234567890"
    assert not part.exists()
    assert row_dict(db, "RJ00000001")["status"] == "completed"
    assert db.get_works_status("RJ00000001") == "completed"
    db.close()


def test_oversized_local_file_is_preserved_and_requires_review(tmp_path):
    orc, db, _config, _kernel = make_orchestrator(tmp_path)
    _meta, target, _dl_id, _root = seed_work(orc, db, size=10)
    target.save_path.write_bytes(b"12345678901")

    result = asyncio.run(orc.resume_job("RJ00000001"))

    assert result["status"] == "unrecoverable"
    assert result["unrecoverable"] == 1
    assert target.save_path.read_bytes() == b"12345678901"
    row = row_dict(db, "RJ00000001")
    assert row["status"] == "failed"
    assert "larger than expected" in row["error"]
    db.close()


def test_failed_without_file_retries_from_zero(tmp_path):
    orc, db, _config, _kernel = make_orchestrator(tmp_path)
    seed_work(orc, db, size=10)

    result = asyncio.run(orc.resume_job("RJ00000001"))

    assert result["status"] == "queued"
    assert result["retried_from_zero"] == 1
    assert row_dict(db, "RJ00000001")["downloaded_bytes"] == 0
    db.close()


def test_pause_and_cancel_use_distinct_runtime_markers(tmp_path):
    pause_orc, pause_db, _config, _kernel = make_orchestrator(tmp_path / "pause")
    seed_work(pause_orc, pause_db, status="queued")
    pause_orc.pause_job("RJ00000001")
    assert "RJ00000001" in pause_orc.cancelled_rjs
    assert "RJ00000001" not in pause_orc.user_cancelled_rjs
    assert pause_db.get_works_status("RJ00000001") == "paused"
    assert row_dict(pause_db, "RJ00000001")["status"] == "paused"
    pause_db.close()

    cancel_orc, cancel_db, _config, _kernel = make_orchestrator(tmp_path / "cancel")
    seed_work(cancel_orc, cancel_db, status="queued")
    cancel_orc.cancel_job("RJ00000001")
    assert "RJ00000001" in cancel_orc.cancelled_rjs
    assert "RJ00000001" in cancel_orc.user_cancelled_rjs
    assert cancel_db.get_works_status("RJ00000001") == "cancelled"
    assert row_dict(cancel_db, "RJ00000001")["status"] == "cancelled"
    cancel_db.close()


def test_cancel_never_rewrites_completed_work(tmp_path):
    orc, db, _config, _kernel = make_orchestrator(tmp_path)
    seed_work(orc, db, size=10, status="completed")
    db.execute_write(
        "UPDATE downloads SET status='registered', downloaded_bytes=10 WHERE rj_id=?",
        ("RJ00000001",),
    )

    result = orc.cancel_job("RJ00000001")

    assert result["status"] == "already_terminal"
    assert db.get_works_status("RJ00000001") == "completed"
    assert row_dict(db, "RJ00000001")["status"] == "registered"
    db.close()


def test_cancel_during_prepare_is_persisted_after_prepare_finishes(tmp_path):
    orc, db, _config, _kernel = make_orchestrator(tmp_path)
    meta = WorkMetadata(
        rj_id="RJ00000001", title="Race", circle="Test", cv=[], tags=[],
        price=0, source_url="", dl_count=0, rating=0,
        release_date="", cover_url="",
    )
    root = orc.get_save_path(meta)
    target = SimpleNamespace(id="1", title="track.mp3", save_path=root / "track.mp3", size=10)

    async def prepare(*_args, **_kwargs):
        root.mkdir(parents=True, exist_ok=True)
        db.register(meta, 0, root, status="prepared")
        dl_id = orc._make_dl_id(meta.rj_id, target.id, target.save_path, target.title)
        db.upsert_download(dl_id, meta.rj_id, target.title, str(target.save_path), "queued", 0, 10)
        return meta, [target], root, False

    orc.prepare_work = prepare
    orc.user_cancelled_rjs.add("RJ00000001")
    orc.cancelled_rjs.add("RJ00000001")

    result = asyncio.run(orc.queue_job("RJ00000001"))

    assert result["status"] == "cancelled"
    assert result["during_prepare"] is True
    assert orc.download_queue.qsize() == 0
    assert db.get_works_status("RJ00000001") == "cancelled"
    assert row_dict(db, "RJ00000001")["status"] == "cancelled"
    db.close()


def test_pause_during_prepare_stays_resumable_not_cancelled(tmp_path):
    orc, db, _config, _kernel = make_orchestrator(tmp_path)
    meta = WorkMetadata(
        rj_id="RJ00000001", title="Race", circle="Test", cv=[], tags=[],
        price=0, source_url="", dl_count=0, rating=0,
        release_date="", cover_url="",
    )
    root = orc.get_save_path(meta)
    target = SimpleNamespace(id="1", title="track.mp3", save_path=root / "track.mp3", size=10)

    async def prepare(*_args, **_kwargs):
        root.mkdir(parents=True, exist_ok=True)
        db.register(meta, 0, root, status="prepared")
        dl_id = orc._make_dl_id(meta.rj_id, target.id, target.save_path, target.title)
        db.upsert_download(dl_id, meta.rj_id, target.title, str(target.save_path), "queued", 0, 10)
        return meta, [target], root, False

    orc.prepare_work = prepare
    orc.cancelled_rjs.add("RJ00000001")

    result = asyncio.run(orc.queue_job("RJ00000001"))

    assert result["status"] == "paused"
    assert result["during_prepare"] is True
    assert "RJ00000001" not in orc.user_cancelled_rjs
    assert db.get_works_status("RJ00000001") == "paused"
    assert row_dict(db, "RJ00000001")["status"] == "paused"
    db.close()


def test_explicit_retry_handles_cancelled_work_with_no_download_rows(tmp_path):
    orc, db, _config, _kernel = make_orchestrator(tmp_path)
    meta, _target, _dl_id, _root = seed_work(orc, db, size=10)
    db.execute_write("DELETE FROM downloads WHERE rj_id=?", (meta.rj_id,))
    db.execute_write("UPDATE works SET status='cancelled' WHERE rj_id=?", (meta.rj_id,))
    orc.user_cancelled_rjs.add(meta.rj_id)

    result = asyncio.run(orc.retry_cancelled_job(meta.rj_id))

    assert result["status"] == "queued"
    assert result["count"] == 1
    assert meta.rj_id not in orc.user_cancelled_rjs
    db.close()


def test_cancelled_is_hidden_from_resume_all_but_available_in_filter(tmp_path):
    orc, db, config, _kernel = make_orchestrator(tmp_path)
    seed_work(orc, db, status="queued")
    orc.cancel_job("RJ00000001")

    assert "RJ00000001" not in orc.resume_all()
    service = DownloadService(db, output_dir=config.output_dir, library_paths=config.library_paths)
    page = service.fetch_queue_page(status_filter="cancelled")
    assert [item.rj_id for item in page.items] == ["RJ00000001"]
    assert page.items[0].queue_state == "cancelled"
    assert page.items[0].can_retry is True
    assert page.items[0].progress == 0.0
    db.close()


def test_cover_uses_local_cache_and_preserves_real_extension(tmp_path):
    config = ConfigManager()
    config.output_dir = tmp_path / "Downloads"
    config.cover_fallback_to_direct = False
    db = LibraryVault(tmp_path / "history.db")
    kernel = CoverKernel(
        config,
        payload=b"\x89PNG\r\n\x1a\nimage-data",
        content_type="image/png",
    )
    orc = Orchestrator(kernel, config, db)
    root = tmp_path / "work"

    first = asyncio.run(orc._download_cover("RJ00000001", "https://example/cover", root))
    second = asyncio.run(orc._download_cover("RJ00000001", "https://example/cover", root))

    assert first == root / "cover.png"
    assert second == first
    assert first.read_bytes().startswith(b"\x89PNG")
    assert kernel.calls == [("https://example/cover", "cover", False)]
    assert not (root / ".cover.download.part").exists()
    db.close()


def test_cover_direct_fallback_is_explicit_and_cover_scoped(tmp_path):
    config = ConfigManager()
    config.output_dir = tmp_path / "Downloads"
    config.cover_fallback_to_direct = True
    db = LibraryVault(tmp_path / "history.db")
    kernel = CoverKernel(config, fail_proxy=True)
    orc = Orchestrator(kernel, config, db)

    path = asyncio.run(orc._download_cover("RJ00000001", "https://example/cover", tmp_path / "work"))

    assert path is not None
    assert kernel.calls == [
        ("https://example/cover", "cover", False),
        ("https://example/cover", "cover", True),
    ]
    db.close()


def test_user_facing_source_contracts_cover_all_buttons_and_shell_override():
    root = Path(__file__).resolve().parents[1]
    base = (root / "ui/views/download_view_base.py").read_text(encoding="utf-8")
    shell = (root / "ui/app.py").read_text(encoding="utf-8")
    app_base = (root / "ui/app_base.py").read_text(encoding="utf-8")
    library = (root / "ui/views/library_view.py").read_text(encoding="utf-8")
    tools = (root / "ui/views/tools_view.py").read_text(encoding="utf-8")

    assert "actions.extend([btn_resume, btn_hide, btn_cancel])" in base
    assert "actions.extend([btn_pause, btn_hide, btn_cancel])" in base
    assert "actions.extend([btn_pause, btn_hide, btn_cancel, btn_reconnect])" in base
    assert 'if ns in {"completed", "registered", "verified"}' in base
    assert "resume_cancelled_download" in app_base
    assert 'stats.get("metadata_required", 0)' in shell
    assert 'stats.get("unrecoverable", 0)' in shell
    assert 'cover_src = item.get("metadata_cover_url")' not in library
    assert 'cover_source = detail.get("metadata_cover_url")' not in library
    library_tree = ast.parse(library, filename="ui/views/library_view.py")
    library_class = next(
        node for node in library_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "LibraryView"
    )
    anomaly_method = next(
        node for node in library_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "_apply_anomalies"
    )
    assignments = [
        node for node in ast.walk(anomaly_method)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Attribute)
            and target.attr == "value"
            and isinstance(target.value, ast.Attribute)
            and target.value.attr == "page_info"
            for target in node.targets
        )
    ]
    assert len(assignments) == 1
    page_info_names = {
        node.id for node in ast.walk(assignments[0].value)
        if isinstance(node, ast.Name)
    }
    assert "sort_label" not in page_info_names
    assert "category_label" not in page_info_names
    local_names = {
        node.id for node in ast.walk(anomaly_method)
        if isinstance(node, ast.Name)
    }
    assert "category_label" in local_names  # local loop label remains valid
    assert "advanced_mode_enabled" in tools
    assert "真实执行已冻结" in tools


def test_config_round_trip_keeps_cover_fallback(tmp_path, monkeypatch):
    import core.config as config_module

    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "CONFIG_FILE", config_path)
    config = ConfigManager()
    config.output_dir = tmp_path / "Downloads"
    config.cover_fallback_to_direct = True
    config.save()

    loaded = ConfigManager.load()
    assert loaded.cover_fallback_to_direct is True
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["cover_fallback_to_direct"] is True


def test_missing_registered_file_is_requeued_for_repair(tmp_path):
    orc, db, _config, _kernel = make_orchestrator(tmp_path)
    _meta, target, _dl_id, _root = seed_work(orc, db, size=10, status="completed")
    db.execute_write(
        "UPDATE downloads SET status='registered', downloaded_bytes=10 WHERE rj_id=?",
        ("RJ00000001",),
    )
    assert not target.save_path.exists()

    result = asyncio.run(orc.resume_job("RJ00000001"))

    assert result["status"] == "queued"
    assert result["retried_from_zero"] == 1
    assert row_dict(db, "RJ00000001")["status"] == "queued"
    db.close()


def test_rapid_duplicate_prepare_and_resume_clicks_are_guarded(tmp_path):
    orc, db, _config, _kernel = make_orchestrator(tmp_path)
    orc.preparing_rj_ids.add("RJ00000001")
    result = asyncio.run(orc.queue_job("RJ00000001"))
    assert result["status"] == "already_queued"
    orc.preparing_rj_ids.clear()

    orc.resuming_rj_ids.add("RJ00000001")
    result = asyncio.run(orc._resume_one("RJ00000001"))
    assert result["status"] == "already_queued"
    db.close()


def test_cancel_during_resume_metadata_refresh_does_not_resurrect(tmp_path):
    orc, db, _config, _kernel = make_orchestrator(tmp_path)
    meta = WorkMetadata(
        rj_id="RJ00000001", title="Race", circle="Test", cv=[], tags=[],
        price=0, source_url="", dl_count=0, rating=0,
        release_date="", cover_url="",
    )
    root = orc.get_save_path(meta)
    target = SimpleNamespace(
        id="1", title="track.mp3", save_path=root / "track.mp3",
        size=10, type="audio", children=[],
    )

    async def prepare(*_args, **_kwargs):
        root.mkdir(parents=True, exist_ok=True)
        db.register(meta, 0, root, status="prepared")
        dl_id = orc._make_dl_id(meta.rj_id, target.id, target.save_path, target.title)
        db.upsert_download(
            dl_id, meta.rj_id, target.title, str(target.save_path),
            "queued", 0, 10,
        )
        orc.user_cancelled_rjs.add(meta.rj_id)
        orc.cancelled_rjs.add(meta.rj_id)
        return meta, [target], root, False

    orc.prepare_work = prepare
    result = asyncio.run(orc.resume_job(meta.rj_id))

    assert result["status"] == "cancelled"
    assert result["during_resume_prepare"] is True
    assert orc.download_queue.qsize() == 0
    assert db.get_works_status(meta.rj_id) == "cancelled"
    db.close()


def test_orphan_cancelled_download_is_visible_in_cancelled_filter(tmp_path):
    orc, db, config, _kernel = make_orchestrator(tmp_path)
    _meta, target, dl_id, _root = seed_work(orc, db, status="failed")
    db.execute_write("DELETE FROM works WHERE rj_id=?", ("RJ00000001",))
    db.upsert_download(
        dl_id, "RJ00000001", target.title, str(target.save_path),
        "cancelled", 0, 10,
    )

    service = DownloadService(
        db, output_dir=config.output_dir, library_paths=config.library_paths
    )
    page = service.fetch_queue_page(status_filter="cancelled")

    assert [item.rj_id for item in page.items] == ["RJ00000001"]
    assert page.items[0].cancelled_files == 1
    assert page.summary.cancelled_tasks == 1
    db.close()


def test_cancelled_rows_protect_metadata_but_do_not_block_vacuum(tmp_path):
    from datetime import datetime, timedelta, timezone
    from core.tools_maintenance import preview_metadata_cache_cleanup, preview_vacuum

    orc, db, _config, _kernel = make_orchestrator(tmp_path)
    seed_work(orc, db, status="failed")
    orc.cancel_job("RJ00000001")
    old = (datetime.now(timezone.utc) - timedelta(days=30)).replace(tzinfo=None).isoformat()
    db.execute_write(
        "UPDATE metadata_cache SET fetched_at=?, updated_at=? WHERE rj_id=?",
        (old, old, "RJ00000001"),
    )
    db.close()

    cache_preview = preview_metadata_cache_cleanup(
        tmp_path / "history.db", now=datetime.now(timezone.utc)
    )
    vacuum_preview = preview_vacuum(tmp_path / "history.db")

    assert cache_preview.protected_expired_rows == 1
    assert cache_preview.removable_rows == 0
    assert vacuum_preview["blocked"] is False


def test_writable_probe_failure_cleans_new_directory(tmp_path, monkeypatch):
    import core.settings_validation as validation

    target = tmp_path / "new-output"

    def fail_probe(*_args, **_kwargs):
        raise OSError("probe denied")

    monkeypatch.setattr(validation.tempfile, "mkstemp", fail_probe)
    with pytest.raises(ValueError, match="目录不可写"):
        validation.validate_writable_directory(target)
    assert not target.exists()


def test_source_contracts_include_race_and_completion_guards():
    root = Path(__file__).resolve().parents[1]
    orchestrator = (root / "core/orchestrator.py").read_text(encoding="utf-8")
    service = (root / "core/services/download_service.py").read_text(encoding="utf-8")
    read_models = (root / "core/read_models.py").read_text(encoding="utf-8")

    assert "preparing_rj_ids" in orchestrator
    assert "resuming_rj_ids" in orchestrator
    assert '"Cancelled" if durable_cancel else "Paused"' in orchestrator
    assert "and not blocking_rows" in orchestrator
    assert "Never trust a terminal SQLite label" in orchestrator
    assert "cancelled_files" in service
    assert "cancelled_files: int = 0" in read_models
