"""Issue #19 + review fixes: stable left task list + right file-detail panel.

These tests pin the no-flash behaviour (Control instances are reused across
refreshes instead of being cleared and rebuilt), the right-side detail panel
(file tree with relative-path keys, error + ``.part`` state), selection
highlight, detail pagination, the narrow-window dialog fallback, per-state
action buttons, verified-byte display and the off-UI-thread queue refresh.
"""

from pathlib import Path
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


# ══════════════════════════════════════════════
#  Review #4: verified-byte display, registered semantics
# ══════════════════════════════════════════════

def test_card_uses_verified_bytes_not_stale_db_bytes(view_controller) -> None:
    view, controller = view_controller
    # DB row claims 100 downloaded; the only thing on disk is a 3-byte .part.
    controller.db.conn.execute(
        "UPDATE downloads SET downloaded_bytes=100 WHERE rj_id=?",
        ("RJ00000001",))
    controller.db.conn.commit()

    view.refresh_queue_async(force=True)

    data = view.active_downloads["RJ00000001"]
    assert data["snapshot"].verified_bytes == 3
    view._update_compact_card("RJ00000001")
    assert data["size_text"].value == "3 B / 10 B"


def test_registered_not_forced_to_100_when_verified_incomplete(view_controller) -> None:
    view, _controller = view_controller
    data = view.active_downloads["RJ00000001"]
    data["status"] = "registered"
    # verified_files == 0 (only a 3-byte .part, no final file)
    assert data["snapshot"].verified_files == 0

    view._update_compact_card("RJ00000001")

    assert data["prog_bar"].value < 1.0


def test_detail_summary_uses_verified_bytes(view_controller) -> None:
    view, controller = view_controller
    controller.db.conn.execute(
        "UPDATE downloads SET downloaded_bytes=100 WHERE rj_id=?",
        ("RJ00000001",))
    controller.db.conn.commit()
    view.refresh_queue_async(force=True)
    view._select_rj("RJ00000001")
    assert "3 B / 10 B" in view.detail_summary.value


# ══════════════════════════════════════════════
#  Review #6: unique per-state buttons
# ══════════════════════════════════════════════

def test_paused_card_has_resume_but_no_pause_button(view_controller) -> None:
    view, _controller = view_controller
    import flet as ft
    icons = [b.icon for b in view._build_compact_actions("paused", "RJ00000001")]
    assert ft.Icons.PLAY_ARROW in icons
    assert ft.Icons.PAUSE not in icons


def test_queued_card_has_pause_but_no_resume_button(view_controller) -> None:
    view, _controller = view_controller
    import flet as ft
    icons = [b.icon for b in view._build_compact_actions("queued", "RJ00000001")]
    assert ft.Icons.PAUSE in icons
    assert ft.Icons.PLAY_ARROW not in icons


# ══════════════════════════════════════════════
#  Review #6: file tree — relative-path keys, error, .part
# ══════════════════════════════════════════════

def test_duplicate_titles_get_distinct_tree_rows(view_controller) -> None:
    view, controller = view_controller
    work_path = Path(view.active_downloads["RJ00000001"]["snapshot"].local_path)
    (work_path / "a").mkdir(parents=True, exist_ok=True)
    (work_path / "b").mkdir(parents=True, exist_ok=True)
    controller.db.upsert_download(
        "id-a", "RJ00000001", "same.mp3", str(work_path / "a" / "same.mp3"),
        "paused", 5, 10)
    controller.db.upsert_download(
        "id-b", "RJ00000001", "same.mp3", str(work_path / "b" / "same.mp3"),
        "paused", 7, 10)

    rows = view._file_details("RJ00000001")

    keys = [r["key"] for r in rows]
    assert len(set(keys)) == len(keys)  # no title collision
    same = [r for r in rows if r["title"] == "same.mp3"]
    assert len(same) == 2
    assert any(r["rel"] == ["a", "same.mp3"] for r in rows)
    assert any(r["rel"] == ["b", "same.mp3"] for r in rows)


def test_detail_panel_renders_folder_hierarchy(view_controller) -> None:
    view, controller = view_controller
    work_path = Path(view.active_downloads["RJ00000001"]["snapshot"].local_path)
    sub = work_path / "sub"
    sub.mkdir(parents=True, exist_ok=True)
    controller.db.upsert_download(
        "n1", "RJ00000001", "nested.mp3", str(sub / "nested.mp3"),
        "downloading", 2, 10)
    controller.db.conn.commit()

    view._select_rj("RJ00000001")

    folder_keys = [k for k in view._detail_rows if k.startswith("folder:")]
    assert folder_keys
    assert view._detail_rows_by_title.get("nested.mp3") is not None


def test_detail_row_shows_error_and_part_state(view_controller) -> None:
    view, controller = view_controller
    work_path = Path(view.active_downloads["RJ00000001"]["snapshot"].local_path)
    controller.db.upsert_download(
        "err1", "RJ00000001", "broken.mp3", str(work_path / "broken.mp3"),
        "failed", 4, 10, error="signed url expired")
    controller.db.upsert_download(
        "part1", "RJ00000001", "partial.mp3", str(work_path / "partial.mp3"),
        "paused", 6, 10)
    controller.db.conn.commit()

    view._select_rj("RJ00000001")

    broken = view._detail_rows_by_title["broken.mp3"]
    assert "signed url expired" in broken.controls[2].value
    partial = view._detail_rows_by_title["partial.mp3"]
    assert ".part" in partial.controls[2].value


# ══════════════════════════════════════════════
#  Review #3: queue fetch + disk verification OFF the UI thread
# ══════════════════════════════════════════════

class _DeferredController(FakeController):
    def __init__(self, tmp_path: Path):
        super().__init__(tmp_path)
        self.pending = []

    def run_blocking(self, function, on_success=None, **_kwargs):
        self.pending.append((function, on_success))


def _deferred_view(tmp_path: Path):
    controller = _DeferredController(tmp_path)
    controller.seed_paused(tmp_path)
    view = DownloadView(controller)
    return view, controller


def test_queue_query_is_deferred_off_the_calling_thread(tmp_path) -> None:
    """Review #3: fetch + stat must be handed to run_blocking, not executed
    inline on the UI thread."""
    view, controller = _deferred_view(tmp_path)
    try:
        # __init__ runs load_queue + reload_queue_from_database, both deferred.
        assert len(controller.pending) == 2
        assert view.active_downloads == {}
        # A refresh while one is in flight is coalesced, never blocking inline.
        view.refresh_queue_async(force=True)
        assert len(controller.pending) == 2
    finally:
        controller.db.close()


def test_generation_token_drops_stale_snapshot(tmp_path) -> None:
    """Review #3: a superseded in-flight snapshot is never applied; the latest
    request relaunches with the newest filter/page."""
    view, controller = _deferred_view(tmp_path)
    try:
        # init: pending[0]=load(gen1), pending[1]=reload(gen2); in-flight=True
        view._on_filter_change(
            SimpleNamespace(control=SimpleNamespace(value="all")))  # supersede
        assert len(controller.pending) == 2  # marked pending, no new query yet

        _, render_reload = controller.pending[1]   # gen2 — now stale
        render_reload(view.download_service.apply_disk_verification(
            view.download_service.fetch_queue_page(
                status_filter="working", page=1, page_size=24)))
        # The stale "working" snapshot must NOT be applied.
        assert view.queue_model is None

        # The pending flag relaunched a fresh query with the new filter.
        assert len(controller.pending) == 3
        query_b, render_b = controller.pending[2]
        render_b(query_b())

        assert view.queue_model is not None
        assert set(view.active_downloads) == {"RJ00000001"}
    finally:
        controller.db.close()
