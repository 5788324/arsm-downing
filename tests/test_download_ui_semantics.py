import json
from pathlib import Path
from types import SimpleNamespace

import ui.views.download_view as download_module
from ui.views.download_view import DownloadView
from ui.views.settings_view import SettingsView


class FakeDb:
    def __init__(self, work_path: Path | None = None):
        self.work_path = work_path

    def get_pending_rj_ids(self):
        return {"RJ00000001"}

    def get_works_status(self, _rj_id):
        return "prepared"

    def get_downloads_summary(self, _rj_id):
        return {"paused": 1}

    def get_downloads_by_rj(self, _rj_id):
        return [{
            "track_title": "track.mp3",
            "downloaded_bytes": 3,
            "total_bytes": 10,
            "status": "paused",
        }]

    def search(self, *_args, **_kwargs):
        return []

    def get_metadata_cache(self, _rj_id, **_kwargs):
        return None

    def get_work(self, _rj_id):
        if self.work_path is None:
            return None
        return {"local_path": str(self.work_path)}


class FakeController:
    def __init__(self, tmp_path: Path):
        self.db = FakeDb()
        self.config = SimpleNamespace(
            output_dir=tmp_path / "Downloads",
            dir_template="{rj_id} {title}",
            work_concurrency=1,
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
        self.calls = []
        self.snacks = []

    def start_download(self, rj_id, **kwargs):
        self.calls.append(("start", rj_id, kwargs))

    def reconnect_download(self, rj_id):
        self.calls.append(("reconnect", rj_id, {}))

    def cancel_download(self, rj_id):
        self.calls.append(("cancel", rj_id, {}))

    def pause_all_downloads(self):
        self.calls.append(("pause_all", "", {}))

    def resume_all_downloads(self):
        self.calls.append(("resume_all", "", {}))

    def show_snack(self, text):
        self.snacks.append(text)


def make_view(monkeypatch, tmp_path: Path) -> tuple[DownloadView, FakeController]:
    queue_file = tmp_path / "queue.json"
    queue_file.write_text(json.dumps({
        "RJ00000001": {
            "status": "已暂停",
            "tracks": {"track.mp3": {"downloaded": 3, "total": 10, "status": "paused"}},
        }
    }), encoding="utf-8")
    monkeypatch.setattr(download_module, "QUEUE_FILE", queue_file)
    monkeypatch.setattr(DownloadView, "_refresh_queue", lambda self: None)
    controller = FakeController(tmp_path)
    return DownloadView(controller), controller


def test_load_queue_preserves_paused_track_progress(monkeypatch, tmp_path: Path) -> None:
    view, _controller = make_view(monkeypatch, tmp_path)
    tracks = view.active_downloads["RJ00000001"]["tracks"]
    assert tracks["track.mp3"]["downloaded"] == 3
    assert tracks["track.mp3"]["total"] == 10


def test_force_duplicate_reaches_core_flag(monkeypatch, tmp_path: Path) -> None:
    view, controller = make_view(monkeypatch, tmp_path)
    monkeypatch.setattr(view, "build_queue_item", lambda *_args, **_kwargs: None)
    view._force_download("RJ00000001")
    assert controller.calls[-1] == (
        "start", "RJ00000001", {"allow_duplicate": True})


def test_reconnect_uses_one_sequential_controller_action(monkeypatch, tmp_path: Path) -> None:
    view, controller = make_view(monkeypatch, tmp_path)
    view._reconnect_job("RJ00000001")
    assert controller.calls[-1][0] == "reconnect"
    assert not any(call[0] == "start" for call in controller.calls)


def test_open_directory_uses_database_canonical_path(monkeypatch, tmp_path: Path) -> None:
    view, controller = make_view(monkeypatch, tmp_path)
    canonical = tmp_path / "migrated" / "RJ00000001"
    canonical.mkdir(parents=True)
    controller.db.work_path = canonical
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
    view = SettingsView(controller)
    assert view.work_concurrency_slider.value == 1
    assert view.file_concurrency_slider.value == 4

    view.dir_input.value = str(tmp_path / "output")
    view.work_concurrency_slider.value = 3
    view.file_concurrency_slider.value = 9
    view.on_save(None)

    assert controller.config.work_concurrency == 3
    assert controller.config.file_concurrency == 9
    assert controller.config.max_concurrent == 9


def test_queue_summary_shows_counts_speed_and_button_availability(
        monkeypatch, tmp_path: Path) -> None:
    view, _controller = make_view(monkeypatch, tmp_path)
    view.active_downloads["RJ00000002"] = {
        "status": "下载中",
        "tracks": {},
        "control": None,
    }
    view.global_speed_bps = 6 * 1024 * 1024

    view._update_queue_summary(["RJ00000001", "RJ00000002"])

    assert "下载中 1" in view.queue_summary.value
    assert "暂停 1" in view.queue_summary.value
    assert "总速度 6.0 MB/s" in view.queue_summary.value
    assert view.btn_pause_all.disabled is False
    assert view.btn_resume_all.disabled is False


def test_progress_uses_work_speed_for_card_and_global_speed_for_header(
        monkeypatch, tmp_path: Path) -> None:
    view, _controller = make_view(monkeypatch, tmp_path)
    rj_id = "RJ00000001"
    view.active_downloads[rj_id]["status"] = "下载中"
    monkeypatch.setattr(view, "build_queue_item", lambda *_args, **_kwargs: None)

    event = SimpleNamespace(
        rj_id=rj_id,
        track_title="track.mp3",
        downloaded_bytes=5,
        total_bytes=10,
        status="downloading",
        work_speed_bps=2 * 1024 * 1024,
        track_speed_bps=1 * 1024 * 1024,
        global_speed_bps=6 * 1024 * 1024,
        eta_seconds=5,
    )

    view.update_track_progress(event)

    assert view.active_downloads[rj_id]["last_speed_bps"] == 2 * 1024 * 1024
    assert view.global_speed_bps == 6 * 1024 * 1024
    assert "总速度 6.0 MB/s" in view.queue_summary.value


def test_completed_work_is_removed_from_active_queue_immediately(
        monkeypatch, tmp_path: Path) -> None:
    view, _controller = make_view(monkeypatch, tmp_path)

    view.update_work_status("RJ00000001", "Completed")

    assert "RJ00000001" not in view.active_downloads
    assert "显示 0 项" in view.queue_summary.value
    assert view.btn_pause_all.disabled is True
    assert view.btn_resume_all.disabled is True


def test_batch_controls_delegate_to_controller(monkeypatch, tmp_path: Path) -> None:
    view, controller = make_view(monkeypatch, tmp_path)

    view._batch_pause()
    view._batch_resume()

    assert ("pause_all", "", {}) in controller.calls
    assert ("resume_all", "", {}) in controller.calls
