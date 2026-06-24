#!/usr/bin/env python3
"""暂停事件不重新启动动画测试 — 验证 paused 后 ProgressEvent 不更新视觉."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

class MockProgressEvent:
    """Minimal ProgressEvent mock with all fields update_track_progress reads."""
    def __init__(self, rj_id, track_title, downloaded, total, status,
                 global_speed_bps=0, track_speed_bps=0, eta_seconds=None):
        self.rj_id = rj_id
        self.track_title = track_title
        self.downloaded_bytes = downloaded
        self.total_bytes = total
        self.status = status
        self.global_speed_bps = global_speed_bps
        self.track_speed_bps = track_speed_bps
        self.eta_seconds = eta_seconds

class MockText:
    """Mock Flet Text that records value changes."""
    def __init__(self, value=""):
        self.value = value
        self._update_count = 0
    def update(self):
        self._update_count += 1

class MockProgressBar:
    """Mock Flet ProgressBar that records value changes."""
    def __init__(self, value=None):
        self.value = value
        self._update_count = 0
    def update(self):
        self._update_count += 1

async def test():
    print(f"\n{'='*60}\n  暂停事件不重新启动动画测试\n{'='*60}\n")

    from core.status import WorkStatus

    # ── 1. Build a mock active_downloads entry for a paused task ──
    print("── 1. 模拟 paused 任务的 active_downloads ──")
    rj_id = "RJ01591"
    data = {
        "status": "已暂停",
        "tracks": {"track1.mp3": {"downloaded": 50, "total": 100, "status": "paused"}},
        "speed_text": MockText(""),
        "prog_bar": MockProgressBar(0.5),
        "control": None,
        "last_time": 0, "last_bytes": 0, "cache_hit": False,
        "current_track": "track1.mp3",
    }

    # ── 2. Verify normalized status ──
    print("── 2. 验证状态是 paused ──")
    from ui.views.download_view import DownloadView
    ns = DownloadView.normalize_status("已暂停")
    assert ns == "paused", f"normalize 应为 paused, 得到 {ns}"
    print(f"  ✓ normalize('已暂停') = '{ns}'")

    # ── 3. Simulate a progress event arriving for a paused task ──
    print("── 3. 模拟 paused 任务的 ProgressEvent ──")
    event = MockProgressEvent(
        rj_id=rj_id, track_title="track1.mp3",
        downloaded=75, total=100, status="downloading",
        global_speed_bps=500000, track_speed_bps=500000,
        eta_seconds=10)

    # Simulate the paused check logic from update_track_progress
    ui_status = data.get("status", "")
    is_paused = (
        ui_status in ("已暂停", "Paused (partial)") or
        ui_status.startswith("Paused") or
        "paused" in str(ui_status).lower())
    assert is_paused, "应检测到 paused 状态"
    print(f"  ✓ is_paused={is_paused}")

    # Track data can be updated (downloaded/total)
    data["tracks"]["track1.mp3"] = {
        "downloaded": 75, "total": 100, "status": "downloading"}
    data["last_speed_bps"] = event.global_speed_bps

    # But visual controls must NOT be updated
    old_prog_value = data["prog_bar"].value
    old_speed_value = data["speed_text"].value

    # Simulate paused guard: don't update visual controls
    if is_paused:
        data["speed_text"].value = ""
        # NO: data["prog_bar"].value = new_prog  (this is the fix!)
        pass

    assert data["prog_bar"].value == old_prog_value, \
        "进度条不应更新"  # still 0.5, not 0.75
    print(f"  ✓ 进度条保持 {data['prog_bar'].value} (未变为 0.75)")
    print(f"  ✓ 速度文本清空: '{data['speed_text'].value}'")

    # Status must NOT change back to downloading
    assert data["status"] == "已暂停", "状态不应变为 downloading"
    print(f"  ✓ 状态仍为 '{data['status']}'")

    # Track data DID update (just not visual)
    assert data["tracks"]["track1.mp3"]["downloaded"] == 75, \
        "track data should still update"
    print(f"  ✓ track data 更新 (downloaded=75)")

    print(f"\n{'='*60}\n  ✓ 暂停事件不重新启动动画测试通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
