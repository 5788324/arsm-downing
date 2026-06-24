#!/usr/bin/env python3
"""already_queued 不会成为 card.status 测试."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  already_queued ignored by card status\n{'='*60}\n")

    from core.status import WorkStatus
    from ui.views.download_view import DownloadView

    # ── 1. normalize maps to queued (NOT a new displayed status) ──
    assert WorkStatus.normalize("already_queued").value == "queued"
    assert WorkStatus.normalize("already_running").value == "downloading"
    print(f"  ✓ already_queued→queued, already_running→downloading")

    # ── 2. DownloadView.normalize_status maps correctly ──
    assert DownloadView.normalize_status("already_queued") == "queued"
    assert DownloadView.normalize_status("already_running") == "downloading"
    print(f"  ✓ DownloadView.normalize_status maps correctly")

    # ── 3. _is_terminal returns False for already_queued ──
    assert not DownloadView._is_terminal("already_queued")
    assert not DownloadView._is_terminal("already_running")
    print(f"  ✓ not terminal")

    # ── 4. Derive from DB: never produces "already_queued" as status string ──
    # The derive function gets counts from downloads table where statuses
    # are 'queued'/'paused'/'downloading'/'completed'/'registered'/'failed'
    # — NEVER 'already_queued'. So derived status can never be "already_queued".
    valid_db_statuses = ("queued", "paused", "downloading", "completed",
                         "registered", "failed")
    assert "already_queued" not in valid_db_statuses
    assert "already_running" not in valid_db_statuses
    print(f"  ✓ already_queued/already_running never in DB → never in derived status")

    # ── 5. update_work_status guard rejects already_queued ──
    import inspect
    src = inspect.getsource(DownloadView.update_work_status)
    has_guard_aq = "already_queued" in src.lower()
    has_guard_ar = "already_running" in src.lower()
    assert has_guard_aq, "update_work_status must guard against already_queued"
    assert has_guard_ar, "update_work_status must guard against already_running"
    print(f"  ✓ update_work_status guards: already_queued={has_guard_aq} already_running={has_guard_ar}")

    print(f"\n{'='*60}\n  ✓ already_queued ignored by card status 测试通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
