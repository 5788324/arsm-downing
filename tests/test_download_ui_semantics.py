from pathlib import Path
from types import SimpleNamespace

import pytest

import ui.views.download_view as download_module
from core.database import LibraryVault
from core.models import ProgressEvent, WorkMetadata
from ui.views.download_view import DownloadView
from ui.views.settings_view import SettingsView


class FakePage:
    def __init__(self):
        self.dialog = None

    def update(self):
        return None


class FakeController:
    def __init__(self, tmp_path: Path):
        self.db = LibraryVault(tmp_path / "history.db")
        self.config = SimpleNamespace(
            output_dir=tmp_path / "Downloads",
            dir_template="{rj_id} {title}",
            work_concurrency=1,
            metadata_concurrency=2,
            file_concurrency=4,
            max_concurrent=4,
            metadata_proxy=None,
            cover_proxy=None,
            download_proxy=None,
            download_fallback_to_proxy=False,
            tag_audio=True,
            sort_files=False,
            library_paths=[],
            external_intake_root=None,
            external_quarantine_root=None,
        )
        self.page = FakePage()
        self.orc = SimpleNamespace(active_tasks={}, queued_rj_ids=set())
        self.calls = []
        self.snacks = []

    def seed_paused(self, tmp_path: Path) -> None:
        meta = WorkMetadata(
            rj_id="RJ00000001",
            title="Paused title",
            circle="Circle",
            cv=[],
            tags=[],
            price=0,
            source_url="",
            dl_count=0,
            rating=0.0,
            release_date="",
            cover_url="",
        )
        work_path = tmp_path / "paused"
        work_path.mkdir(parents=True, exist_ok=True)
        self.db.register(meta, 3, work_path, status="paused")
        self.db.upsert_download(
            "file-1",
            meta.rj_id,
            "track.mp3",
            str(work_path / "track.mp3"),
            "paused",
            3,
            10,
        )

    def start_download(self, rj_id, **kwargs):
        self.calls.append(("start", rj_id, kwargs))

    def reconnect_download(self, rj_id):
        self.calls.append(("reconnect", rj_id, {}))

    def cancel_download(self, rj_id):
        self.calls.append(("cancel", rj_id, {}))

    def pause_download(self, rj_id):
        self.calls.append(("pause", rj_id, {}))

    def resume_download(self, rj_id):
        self.calls.append(("resume", rj_id, {}))

    def pause_all_downloads(self):
        self.calls.append(("pause_all", "", {}))

    def resume_all_downloads(self):
        self.calls.append(("resume_all", "", {}))

    def run_blocking(self, function, on_success=None, **_kwargs):
        result = function()
        if on_success:
            on_success(result)
        return result

    def show_snack(self, text):
        self.snacks.append(text)

    def check_achievements(self):
        return None


@pytest.fixture
def view_controller(monkeypatch, tmp_path: Path):
    queue_file = tmp_path / "queue.json"
    monkeypatch.setattr(download_module, "QUEUE_FILE", queue_file)
    controller = FakeController(tmp_path)
    controller.seed_paused(tmp_path)
    view = DownloadView(controller)
    try:
        yield view, controller
    finally:
        controller.db.close()


def test_load_queue_uses_aggregate_snapshot_progress(view_controller) -> None:
    view, _controller = view_controller
    data = view.active_downloads["RJ00000001"]
    snapshot = data["snapshot"]
    assert snapshot.downloaded_bytes == 3
    assert snapshot.total_bytes == 10
    assert snapshot.percent == 30.0
    # Per-file rows are no longer queried once per card during initial load.
    assert data["tracks"] == {}


def test_force_duplicate_reaches_core_flag(view_controller, monkeypatch) -> None:
    view, controller = view_controller
    monkeypatch.setattr(view, "build_queue_item", lambda *_args, **_kwargs: None)
    view._force_download("RJ00000001")
    assert controller.calls[-1] == (
        "start", "RJ00000001", {"allow_duplicate": True})


def test_reconnect_uses_one_sequential_controller_action(view_controller) -> None:
    view, controller = view_controller
    view._reconnect_job("RJ00000001")
    assert controller.calls[-1][0] == "reconnect"
    assert not any(call[0] == "start" for call in controller.calls)


def test_open_directory_uses_snapshot_canonical_path(
    view_controller,
    monkeypatch,
) -> None:
    view, _controller = view_controller
    canonical = Path(
        view.active_downloads["RJ00000001"]["snapshot"].local_path
    )
    opened = []
    monkeypatch.setattr(download_module.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        download_module.subprocess,
        "run",
        lambda args, check=False: opened.append((args, check)),
    )

    view._open_work_dir("RJ00000001")

    assert opened == [(["xdg-open", str(canonical)], False)]


def test_batch_preview_does_not_enqueue_until_confirmed(view_controller) -> None:
    view, controller = view_controller
    preview = view.queue_query.preview_input(
        "RJ00000002 RJ00000003",
        active_rj_ids=set(view.active_downloads),
    )
    view._show_batch_preview(preview)
    assert controller.calls == []
    assert controller.page.dialog.open is True

    view._confirm_batch_preview(preview)
    starts = [call for call in controller.calls if call[0] == "start"]
    assert [call[1] for call in starts] == ["RJ00000002", "RJ00000003"]


def test_live_progress_stays_in_memory_without_queue_file_write(
    view_controller,
    monkeypatch,
) -> None:
    view, _controller = view_controller
    saves = []
    monkeypatch.setattr(view, "save_queue", lambda: saves.append(True))
    view.update_track_progress(
        ProgressEvent(
            rj_id="RJ00000001",
            track_id="file-1",
            track_title="track.mp3",
            downloaded_bytes=5,
            total_bytes=10,
            percent=50.0,
            track_speed_bps=100,
            work_speed_bps=100,
            global_speed_bps=100,
            eta_seconds=1,
            status="downloading",
        )
    )
    assert saves == []
    assert view.active_downloads["RJ00000001"]["tracks"]["track.mp3"]["downloaded"] == 5


def test_settings_edit_real_concurrency_fields(tmp_path: Path) -> None:
    controller = FakeController(tmp_path)
    controller.config.save = lambda: None
    try:
        view = SettingsView(controller)
        assert view.work_concurrency_slider.value == 1
        assert view.metadata_concurrency_slider.value == 2
        assert view.file_concurrency_slider.value == 4

        view.dir_input.value = str(tmp_path / "output")
        view.work_concurrency_slider.value = 3
        view.metadata_concurrency_slider.value = 5
        view.file_concurrency_slider.value = 9
        view.on_save(None)

        assert controller.config.work_concurrency == 3
        assert controller.config.metadata_concurrency == 5
        assert controller.config.file_concurrency == 9
        assert controller.config.max_concurrent == 9
    finally:
        controller.db.close()


def test_queue_refresh_failure_restores_refresh_control(
    view_controller,
    monkeypatch,
) -> None:
    view, controller = view_controller

    def fail_query(**_kwargs):
        raise RuntimeError("read failed")

    monkeypatch.setattr(view.queue_query, "fetch_page", fail_query)
    view.refresh_queue_async()

    assert view._queue_refreshing is False
    assert view.queue_refresh_btn.disabled is False
    assert controller.snacks[-1] == "队列读取失败: read failed"
