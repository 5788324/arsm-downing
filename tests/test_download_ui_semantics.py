from pathlib import Path
from types import SimpleNamespace

import pytest

import ui.views.download_view as download_module
from core.database import LibraryVault
from core.models import ProgressEvent, WorkMetadata
from core.read_models import BatchEnqueuePreview
from ui.views.download_view import DownloadView
from ui.views.settings_view import SettingsView


class FakePage:
    def __init__(self):
        self.dialog = None
        self.overlay = []
        self.opened_dialogs = []
        self.closed_dialogs = []

    def update(self):
        return None

    def open(self, dialog):
        self.dialog = dialog
        dialog.open = True
        self.opened_dialogs.append(dialog)

    def close(self, dialog):
        dialog.open = False
        self.closed_dialogs.append(dialog)


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
            cv=[], tags=[], price=0,
            source_url="", dl_count=0, rating=0.0,
            release_date="", cover_url="",
        )
        work_path = tmp_path / "paused"
        work_path.mkdir(parents=True, exist_ok=True)
        self.db.register(meta, 3, work_path, status="paused")
        self.db.upsert_download(
            "file-1", meta.rj_id, "track.mp3",
            str(work_path / "track.mp3"), "paused", 3, 10,
        )
        # P0-D: progress is disk-verified, so a real .part must exist on disk
        # for the snapshot to report 30% instead of 0%.
        (work_path / "track.mp3.part").write_bytes(b"abc")

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
    assert snapshot.progress == 0.3
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


def test_open_directory_uses_snapshot_canonical_path(view_controller, monkeypatch) -> None:
    view, _controller = view_controller
    canonical = Path(view.active_downloads["RJ00000001"]["snapshot"].local_path)
    opened = []
    monkeypatch.setattr(download_module.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        download_module.subprocess, "run",
        lambda args, check=False: opened.append((args, check)),
    )
    view._open_work_dir("RJ00000001")
    assert opened == [(["xdg-open", str(canonical)], False)]


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


def test_queue_summary_shows_counts_speed_and_button_availability(view_controller) -> None:
    view, _controller = view_controller
    view.queue_model = None
    view.active_downloads["RJ00000002"] = {
        "status": "下载中", "tracks": {}, "control": None
    }
    view.global_speed_bps = 6 * 1024 * 1024
    view._update_queue_summary()
    assert "暂停 1" in view.queue_summary.value
    assert "总速度 6.0 MB/s" in view.queue_summary.value
    assert view.btn_pause_all.disabled is False
    assert view.btn_resume_all.disabled is False


def test_progress_uses_work_speed_for_card_and_global_speed_for_header(
    view_controller, monkeypatch
) -> None:
    view, _controller = view_controller
    rj_id = "RJ00000001"
    view.queue_model = None
    view.active_downloads[rj_id]["status"] = "下载中"
    monkeypatch.setattr(view, "build_queue_item", lambda *_args, **_kwargs: None)
    event = ProgressEvent(
        rj_id=rj_id, track_id="file-1", track_title="track.mp3",
        downloaded_bytes=5, total_bytes=10, percent=50.0,
        work_speed_bps=2 * 1024 * 1024,
        track_speed_bps=1 * 1024 * 1024,
        global_speed_bps=6 * 1024 * 1024,
        eta_seconds=5, status="downloading",
    )
    view.update_track_progress(event)
    assert view.active_downloads[rj_id]["last_speed_bps"] == 2 * 1024 * 1024
    assert view.global_speed_bps == 6 * 1024 * 1024
    assert "总速度 6.0 MB/s" in view.queue_summary.value


def test_completed_work_is_removed_from_active_queue_immediately(view_controller) -> None:
    view, _controller = view_controller
    view.update_work_status("RJ00000001", "Completed")
    assert "RJ00000001" not in view.active_downloads
    assert view.btn_pause_all.disabled is True
    assert view.btn_resume_all.disabled is True


def test_filter_applies_when_background_callback_is_unavailable(view_controller) -> None:
    view, controller = view_controller
    controller.run_blocking = lambda *_args, **_kwargs: None
    view._on_filter_change(SimpleNamespace(control=SimpleNamespace(value="paused")))
    assert view.queue_filter == "paused"
    assert view.queue_model.total_items == 1
    assert set(view.active_downloads) == {"RJ00000001"}


def test_batch_controls_delegate_to_controller(view_controller) -> None:
    view, controller = view_controller
    view._batch_pause()
    view._batch_resume()
    assert ("pause_all", "", {}) in controller.calls
    assert ("resume_all", "", {}) in controller.calls


def test_batch_preview_does_not_treat_render_cache_as_runtime_active(
    view_controller, monkeypatch
) -> None:
    view, controller = view_controller
    controller.db.conn.execute(
        "INSERT INTO works(rj_id, title, status) VALUES (?, ?, ?)",
        ("RJ00000007", "review fixture", "legacy_fixture"),
    )
    controller.db.conn.commit()
    # A rendered card is not proof that its work has a live runtime worker.
    view.active_downloads["RJ00000007"] = {"status": "需要复核", "tracks": {}}
    captured = []
    monkeypatch.setattr(view, "_show_batch_preview", lambda preview: captured.append(preview))

    view.process_input("RJ00000007")

    assert captured[0].needs_review == ("RJ00000007",)
    assert captured[0].already_active == ()


def test_batch_preview_has_no_enqueue_until_confirmed(view_controller) -> None:
    view, controller = view_controller
    preview = view.download_service.preview_enqueue("RJ00000002 RJ00000003")
    view._show_batch_preview(preview)
    assert controller.calls == []
    dialog = controller.page.dialog
    assert dialog.open is True
    view._confirm_preview(dialog, preview)
    starts = [call[1] for call in controller.calls if call[0] == "start"]
    assert starts == ["RJ00000002", "RJ00000003"]


def test_inactive_download_page_suppresses_card_rebuild(view_controller, monkeypatch) -> None:
    view, _controller = view_controller
    builds = []
    monkeypatch.setattr(view, "build_queue_item", lambda *_a, **_k: builds.append(True))
    view.set_active(False)
    view.update_track_progress(ProgressEvent(
        rj_id="RJ00000001", track_id="file-1", track_title="track.mp3",
        downloaded_bytes=6, total_bytes=10, percent=60.0,
        work_speed_bps=100, track_speed_bps=100,
        global_speed_bps=100, eta_seconds=1, status="downloading",
    ))
    assert builds == []
    assert view.global_speed_bps == 100


def _durable_state(controller: FakeController) -> tuple[int, int, tuple[str, ...]]:
    works = int(controller.db.conn.execute("SELECT COUNT(*) FROM works").fetchone()[0])
    downloads = int(
        controller.db.conn.execute("SELECT COUNT(*) FROM downloads").fetchone()[0]
    )
    output_dir = Path(controller.config.output_dir)
    files = tuple(
        sorted(str(path.relative_to(output_dir)) for path in output_dir.rglob("*") if path.is_file())
    ) if output_dir.exists() else ()
    return works, downloads, files


def _mixed_preview() -> BatchEnqueuePreview:
    return BatchEnqueuePreview(
        ready=("RJ00000002", "RJ00000008"),
        invalid_tokens=("bad",),
        duplicate_input=("RJ00000002",),
        already_active=("RJ00000003",),
        already_in_queue=("RJ00000004",),
        already_in_library=("RJ00000005",),
        already_completed=("RJ00000006",),
        needs_review=("RJ00000007",),
        reasons={"RJ00000007": "未知/历史状态：legacy"},
    )


def test_batch_button_uses_in_app_paste_dialog_not_file_picker(view_controller) -> None:
    view, controller = view_controller
    assert view.batch_btn.text == "批量粘贴"
    assert view.file_picker not in controller.page.overlay

    dialog = view._open_batch_paste_dialog()

    assert controller.page.dialog is dialog
    assert dialog.open is True
    assert controller.page.opened_dialogs == [dialog]
    assert view._batch_paste_input.multiline is True
    assert view._batch_paste_input.min_lines == 8
    assert view._batch_paste_input.value in (None, "")


def test_batch_paste_cancel_has_zero_side_effects(view_controller) -> None:
    view, controller = view_controller
    before = _durable_state(controller)
    calls_before = list(controller.calls)
    dialog = view._open_batch_paste_dialog()
    view._batch_paste_input.value = "RJ00000002 bad RJ00000002"

    view._close_batch_paste_dialog(dialog)

    assert dialog.open is False
    assert controller.page.closed_dialogs == [dialog]
    assert controller.calls == calls_before
    assert _durable_state(controller) == before


def test_batch_paste_preview_cancel_has_zero_side_effects(
    view_controller, monkeypatch
) -> None:
    view, controller = view_controller
    preview = _mixed_preview()
    monkeypatch.setattr(
        view.download_service, "preview_enqueue", lambda *_args, **_kwargs: preview
    )
    before = _durable_state(controller)
    calls_before = list(controller.calls)
    input_dialog = view._open_batch_paste_dialog()
    view._batch_paste_input.value = "mixed input"

    view._submit_batch_paste(input_dialog, view._batch_paste_input)
    preview_dialog = controller.page.dialog

    assert preview_dialog is not input_dialog
    assert preview_dialog.open is True
    assert controller.calls == calls_before
    assert _durable_state(controller) == before

    view._close_preview(preview_dialog)
    assert controller.calls == calls_before
    assert _durable_state(controller) == before


def test_batch_paste_confirm_enqueues_only_ready_items(
    view_controller, monkeypatch
) -> None:
    view, controller = view_controller
    preview = _mixed_preview()
    monkeypatch.setattr(
        view.download_service, "preview_enqueue", lambda *_args, **_kwargs: preview
    )
    input_dialog = view._open_batch_paste_dialog()
    view._batch_paste_input.value = "mixed input"

    view._submit_batch_paste(input_dialog, view._batch_paste_input)
    preview_dialog = controller.page.dialog
    view._confirm_preview(preview_dialog, preview)

    starts = [call[1] for call in controller.calls if call[0] == "start"]
    assert starts == ["RJ00000002", "RJ00000008"]
    assert "RJ00000003" not in starts
    assert "RJ00000004" not in starts
    assert "RJ00000005" not in starts
    assert "RJ00000006" not in starts
    assert "RJ00000007" not in starts


def test_batch_paste_dialog_reopens_empty_after_cancel(view_controller) -> None:
    view, _controller = view_controller
    first = view._open_batch_paste_dialog()
    view._batch_paste_input.value = "RJ00000002"
    view._close_batch_paste_dialog(first)

    second = view._open_batch_paste_dialog()

    assert second is not first
    assert view._batch_paste_input.value in (None, "")
