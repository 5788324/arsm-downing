"""Issue #19: stable left task list + right file-detail panel.

These tests pin the no-flash behaviour (Control instances are reused across
refreshes instead of being cleared and rebuilt), the right-side detail panel,
selection highlight, detail pagination and the narrow-window dialog fallback.
"""

from types import SimpleNamespace

import pytest

import ui.views.download_view as download_module
from core.models import ProgressEvent
from ui.theme import ACCENT_PRIMARY
from ui.views.download_view import DownloadView
from tests.test_download_ui_semantics import FakeController, FakePage


@pytest.fixture
def view_controller(monkeypatch, tmp_path):
    queue_file = tmp_path / "queue.json"
    monkeypatch.setattr(download_module, "QUEUE_FILE", queue_file)
    controller = FakeController(tmp_path)
    controller.seed_paused(tmp_path)
    view = DownloadView(controller)
    try:
        yield view, controller
    finally:
        controller.db.close()


def _seed_tracks(view, rj_id: str, count: int) -> None:
    data = view.active_downloads.setdefault(rj_id, {
        "status": "下载中", "tracks": {}, "control": None,
    })
    for i in range(count):
        data["tracks"][f"track-{i:03d}.mp3"] = {
            "downloaded": i * 10,
            "total": 100,
            "status": "downloading" if i % 3 else "completed",
        }


def test_stable_card_control_is_reused_across_refreshes(view_controller) -> None:
    view, _controller = view_controller
    rj_id = "RJ00000001"
    first = view._card_controls[rj_id]
    assert first is not None
    assert first in view.queue_list.controls

    view._render_queue_page()

    assert view._card_controls[rj_id] is first
    assert view.queue_list.controls.count(first) == 1


def test_rendering_drops_cards_that_left_the_page(view_controller) -> None:
    view, _controller = view_controller
    view.active_downloads["RJ00000002"] = {"status": "下载中", "tracks": {}}
    view._render_queue_page()
    assert "RJ00000002" in view._card_controls

    view.active_downloads.pop("RJ00000002", None)
    view._render_queue_page()

    assert "RJ00000002" not in view._card_controls


def test_select_rj_renders_detail_panel_rows(view_controller) -> None:
    view, _controller = view_controller
    _seed_tracks(view, "RJ00000002", 3)
    view._render_queue_page()

    view._select_rj("RJ00000002")

    assert view._selected_rj == "RJ00000002"
    assert view.detail_title.value == "RJ00000002"
    assert len(view.detail_scroll.controls) == 3
    assert "3 个文件" in view.detail_header_more.value
    assert view._detail_rows


def test_detail_rows_are_stable_and_progress_is_driven(view_controller) -> None:
    view, _controller = view_controller
    _seed_tracks(view, "RJ00000002", 2)
    view._render_queue_page()
    view._select_rj("RJ00000002")

    row = view.detail_scroll.controls[0]
    assert row.controls[1].value == "track-000.mp3"
    assert row.controls[3].value == 0.0
    assert row.controls[4].value == "0%"


def test_selection_highlight_left_accent_on_card(view_controller) -> None:
    view, _controller = view_controller
    _seed_tracks(view, "RJ00000002", 1)
    view._render_queue_page()
    container = view._card_controls["RJ00000002"]

    view._select_rj("RJ00000002")

    assert container.border.left.color == ACCENT_PRIMARY


def test_detail_pagination_over_page_size(view_controller) -> None:
    view, _controller = view_controller
    _seed_tracks(view, "RJ00000002", view._detail_page_size + 10)
    view._render_queue_page()
    view._select_rj("RJ00000002")

    assert len(view.detail_scroll.controls) == view._detail_page_size
    assert view.detail_next_btn.disabled is False
    assert view.detail_prev_btn.disabled is True

    view._detail_next()

    assert len(view.detail_scroll.controls) == 10
    assert view.detail_prev_btn.disabled is False
    assert view.detail_next_btn.disabled is True
    assert "201" in view.detail_header_more.value

    view._detail_prev()

    assert len(view.detail_scroll.controls) == view._detail_page_size


def test_narrow_window_select_falls_back_to_dialog(view_controller) -> None:
    view, _controller = view_controller
    # In production Flet assigns .page on mount; the base detail dialog needs it.
    view.page = view.app_controller.page
    view.app_controller.page.width = 800
    view.app_controller.orc.get_track_detail_for_ui = (
        lambda *args, **kwargs: [])
    _seed_tracks(view, "RJ00000002", 1)
    view._render_queue_page()

    view._select_rj("RJ00000002")

    assert view._selected_rj == "RJ00000002"
    assert view.app_controller.page.dialog is not None
    assert view.app_controller.page.dialog.open is True


def test_live_detail_row_updates_for_selected_rj(view_controller) -> None:
    view, _controller = view_controller
    _seed_tracks(view, "RJ00000002", 1)
    view._render_queue_page()
    view._select_rj("RJ00000002")

    view.update_track_progress(ProgressEvent(
        rj_id="RJ00000002", track_id="file-x", track_title="track-000.mp3",
        downloaded_bytes=60, total_bytes=100, percent=60.0,
        work_speed_bps=1000, track_speed_bps=1000,
        global_speed_bps=2000, eta_seconds=3, status="downloading",
    ))

    row = view._detail_rows["track-000.mp3"]
    assert row.controls[3].value == 0.6
    assert row.controls[4].value == "60%"
    assert view.detail_progress.value == 0.6


def test_removing_selected_rj_clears_selection_and_panel(view_controller) -> None:
    view, _controller = view_controller
    _seed_tracks(view, "RJ00000002", 1)
    view._render_queue_page()
    view._select_rj("RJ00000002")
    assert view._selected_rj == "RJ00000002"

    view.update_work_status("RJ00000002", "Completed")

    assert view._selected_rj is None
    assert view.detail_scroll.controls == []


def test_reselecting_same_rj_is_idempotent(view_controller) -> None:
    view, _controller = view_controller
    _seed_tracks(view, "RJ00000002", 1)
    view._render_queue_page()

    view._select_rj("RJ00000002")
    first_rows = view.detail_scroll.controls
    view._select_rj("RJ00000002")

    assert view.detail_scroll.controls is first_rows
