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
from core.models import ProgressEvent, WorkMetadata
from ui.theme import ACCENT_PRIMARY, SUCCESS
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


def test_duplicate_titles_live_updates_resolve_by_track_id(view_controller) -> None:
    """Review #3: same filename in different dirs — each progress event updates
    its OWN row (track_id), and a redraw does not add a duplicate top node."""
    from core.orchestrator import Orchestrator
    view, controller = view_controller
    rj = "RJ00000001"
    work_path = Path(view.active_downloads[rj]["snapshot"].local_path)
    (work_path / "本篇").mkdir(parents=True, exist_ok=True)
    (work_path / "特典").mkdir(parents=True, exist_ok=True)

    def dlid(track_id: str) -> str:
        return Orchestrator._make_dl_id(rj, track_id, Path("same.mp3"), "same.mp3")

    id1, id2 = dlid("t1"), dlid("t2")
    controller.db.upsert_download(
        id1, rj, "same.mp3", str(work_path / "本篇" / "same.mp3"),
        "downloading", 2, 10)
    controller.db.upsert_download(
        id2, rj, "same.mp3", str(work_path / "特典" / "same.mp3"),
        "downloading", 3, 10)
    controller.db.conn.commit()

    data = view.active_downloads[rj]
    data["_live_tracks"] = {
        "t1": {"track_id": "t1", "title": "same.mp3",
               "downloaded": 2, "total": 10, "status": "downloading"},
        "t2": {"track_id": "t2", "title": "same.mp3",
               "downloaded": 3, "total": 10, "status": "downloading"},
    }
    view._select_rj(rj)

    key1 = view._detail_key_by_track[rj]["t1"]
    key2 = view._detail_key_by_track[rj]["t2"]
    assert key1 != key2
    assert key1 == "本篇/same.mp3"
    assert key2 == "特典/same.mp3"
    # Exactly two rows for same.mp3 (one per directory) — never a top-level dup.
    same_keys = [k for k in view._detail_rows
                 if view._detail_rows[k].controls[1].value == "same.mp3"]
    assert len(same_keys) == 2
    assert "same.mp3" not in view._detail_rows  # no bare-title top-level node

    def progress(track_id: str, downloaded: int):
        return ProgressEvent(
            rj_id=rj, track_id=track_id, track_title="same.mp3",
            downloaded_bytes=downloaded, total_bytes=10, percent=float(downloaded) * 10,
            work_speed_bps=0.0, track_speed_bps=0.0, global_speed_bps=0.0,
            eta_seconds=None, status="downloading",
        )

    view.update_track_progress(progress("t1", 6))
    view.update_track_progress(progress("t2", 7))

    assert view._detail_rows[key1].controls[3].value == 0.6
    assert view._detail_rows[key2].controls[3].value == 0.7

    # A redraw must not create a third "same.mp3" node.
    view._render_detail_panel(rj)
    same_keys = [k for k in view._detail_rows
                 if view._detail_rows[k].controls[1].value == "same.mp3"]
    assert len(same_keys) == 2
    assert view._detail_key_by_track[rj]["t1"] == key1
    assert view._detail_key_by_track[rj]["t2"] == key2
    # Live progress must survive the redraw (each row keeps its own value).
    assert view._detail_rows[key1].controls[3].value == 0.6
    assert view._detail_rows[key2].controls[3].value == 0.7


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
    nested_key = view._detail_key_by_title.get("nested.mp3")
    assert nested_key is not None
    assert view._detail_rows[nested_key] is not None


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

    broken = view._detail_rows[view._detail_key_by_title["broken.mp3"]]
    assert "signed url expired" in broken.controls[2].value
    partial = view._detail_rows[view._detail_key_by_title["partial.mp3"]]
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


def test_startup_issues_exactly_one_deferred_query(tmp_path) -> None:
    """Review #2: startup runs ONE fetch + disk-verification query through the
    same pipeline (load_queue coalesces any reload instead of starting a second
    full query)."""
    view, controller = _deferred_view(tmp_path)
    try:
        assert len(controller.pending) == 1  # exactly one startup query
        assert view.active_downloads == {}
        # A refresh while that query is in flight is coalesced, not a 2nd query.
        view.refresh_queue_async(force=True)
        assert len(controller.pending) == 1
    finally:
        controller.db.close()


def test_generation_token_drops_stale_snapshot(tmp_path) -> None:
    """Review #3: a superseded in-flight snapshot is never applied; the latest
    request relaunches with the newest filter/page."""
    view, controller = _deferred_view(tmp_path)
    try:
        # init: pending[0] = the single startup query (gen1); in-flight=True
        view._on_filter_change(
            SimpleNamespace(control=SimpleNamespace(value="all")))  # supersede
        assert len(controller.pending) == 1  # marked pending, no new query yet

        _, render_startup = controller.pending[0]   # gen1 — now stale
        render_startup(view.download_service.apply_disk_verification(
            view.download_service.fetch_queue_page(
                status_filter="working", page=1, page_size=24)))
        # The stale "working" snapshot must NOT be applied.
        assert view.queue_model is None

        # The pending flag relaunched a fresh query with the new filter.
        assert len(controller.pending) == 2
        query_b, render_b = controller.pending[1]
        render_b(query_b())

        assert view.queue_model is not None
        assert set(view.active_downloads) == {"RJ00000001"}
    finally:
        controller.db.close()


# ══════════════════════════════════════════════
#  Review round 3: authoritative live total progress
# ══════════════════════════════════════════════

def test_live_known_progress_advances_card_and_detail_over_stale_snapshot(
    view_controller,
) -> None:
    """Review #3: once live data exists it wins over the last disk scan —
    both the left card and the right overall bar move."""
    view, _controller = view_controller
    rj = "RJ00000001"
    data = view.active_downloads[rj]
    assert data["snapshot"].verified_progress == 0.3  # 3-byte .part of 10
    data["_live_tracks"] = {
        "t1": {"track_id": "t1", "title": "track.mp3",
               "downloaded": 6, "total": 10, "status": "downloading"},
    }
    view._update_compact_card(rj)
    assert data["prog_bar"].value == 0.6

    view._render_detail_panel(rj)
    assert view.detail_progress.value == 0.6


def test_unknown_size_live_bytes_never_inflate_work_total(view_controller) -> None:
    """Review #3: a huge unknown-size (total=0) live file never enters the
    numerator without a denominator, so a 0-byte known file stays at 0%."""
    view, _controller = view_controller
    rj = "RJ00000001"
    data = view.active_downloads[rj]
    data["_live_tracks"] = {
        "known": {"track_id": "known", "title": "a.mp3",
                  "downloaded": 0, "total": 100, "status": "downloading"},
        "unknown": {"track_id": "unknown", "title": "b.mp3",
                    "downloaded": 100000, "total": 0, "status": "downloading"},
    }
    assert view._get_progress_value(data) == 0.0

    data["_live_tracks"]["known"]["downloaded"] = 50
    assert view._get_progress_value(data) == 0.5


def test_same_title_files_contribute_separately_to_work_total(view_controller) -> None:
    """Review #3: duplicate filenames in different dirs each add to the work
    total (track_id-keyed), instead of collapsing onto one title key."""
    view, _controller = view_controller
    rj = "RJ00000001"
    data = view.active_downloads[rj]
    data["_live_tracks"] = {
        "t1": {"track_id": "t1", "title": "same.mp3",
               "downloaded": 50, "total": 100, "status": "downloading"},
        "t2": {"track_id": "t2", "title": "same.mp3",
               "downloaded": 75, "total": 100, "status": "downloading"},
    }
    assert view._get_progress_value(data) == (50 + 75) / 200


def test_registered_incomplete_work_downgraded_by_service_pipeline(tmp_path) -> None:
    """Review #3 (full chain): SQLite registered → DownloadService → disk
    verification → read model.  Missing files must downgrade the presentation
    state to partial (non-terminal, visible), never green completed 100%."""
    from core.database import LibraryVault
    from core.services.download_service import DownloadService

    vault = LibraryVault(tmp_path / "history.db")
    try:
        work_path = tmp_path / "RJ00000002"
        meta = WorkMetadata(
            rj_id="RJ00000002", title="Reg T", circle="", cv=[], tags=[],
            price=0, dl_count=0, source_url="", rating=0.0,
            release_date="", cover_url="")
        vault.register(meta, 100, work_path, status="registered")
        vault.upsert_download(
            "d1", "RJ00000002", "a.mp3", str(work_path / "a.mp3"),
            "registered", 100, 100)
        service = DownloadService(vault, output_dir=tmp_path)
        page = service.apply_disk_verification(
            service.fetch_queue_page(status_filter="working"),
            status_filter="working")
        item = {i.rj_id: i for i in page.items}["RJ00000002"]
        assert item.queue_state == "partial"
        assert item.is_terminal is False
        assert item.ui_status == "部分完成"
        assert item.verified_progress == 0.0
        assert item.can_resume is True
        # A genuinely complete registered work stays terminal.
        complete_path = tmp_path / "RJ00000003"
        complete_path.mkdir(parents=True, exist_ok=True)
        (complete_path / "b.mp3").write_bytes(b"x" * 100)
        meta3 = WorkMetadata(
            rj_id="RJ00000003", title="Reg Complete", circle="", cv=[], tags=[],
            price=0, dl_count=0, source_url="", rating=0.0,
            release_date="", cover_url="")
        vault.register(meta3, 100, complete_path, status="registered")
        vault.upsert_download(
            "d2", "RJ00000003", "b.mp3", str(complete_path / "b.mp3"),
            "registered", 100, 100)
        page3 = service.apply_disk_verification(
            service.fetch_queue_page(status_filter="working"),
            status_filter="working")
        complete_items = {i.rj_id: i for i in page3.items}
        # Complete registered work is dropped from the active queue (terminal).
        assert "RJ00000003" not in complete_items
    finally:
        vault.close()


def test_registered_incomplete_card_is_not_green_100(view_controller, tmp_path) -> None:
    """Review #3 UI end-to-end: a registered work with missing files renders as
    partial (warning color, verified 0%), never a green 100% card."""
    view, controller = view_controller
    work_path = tmp_path / "RJ00000002"
    meta = WorkMetadata(
        rj_id="RJ00000002", title="Reg T", circle="", cv=[], tags=[],
        price=0, dl_count=0, source_url="", rating=0.0,
        release_date="", cover_url="")
    controller.db.register(meta, 100, work_path, status="registered")
    controller.db.upsert_download(
        "d1", "RJ00000002", "a.mp3", str(work_path / "a.mp3"),
        "registered", 100, 100)
    controller.db.conn.commit()

    view.refresh_queue_async(force=True)

    data = view.active_downloads["RJ00000002"]
    assert data["snapshot"].queue_state == "partial"
    assert data["snapshot"].is_terminal is False
    view._update_compact_card("RJ00000002")
    assert data["prog_bar"].value == 0.0
    assert data["status_text"].color != SUCCESS
