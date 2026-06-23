#!/usr/bin/env python3
"""SpeedMeter 滑动窗口测试 — 验证速度计算、ETA、暂停归零."""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}")
    print(f"  SpeedMeter 测试")
    print(f"{'='*60}\n")

    from core.speed import SpeedMeter, SpeedTracker

    # ── 1. Basic speed calculation ──
    print("── 1. 基本速度计算 ──")
    m = SpeedMeter(window_seconds=5.0)
    assert m.speed_bps == 0.0, "空窗口速度应为 0"
    m.update(0)
    time.sleep(0.5)
    m.update(500_000)  # 500KB in 0.5s → ~1MB/s
    speed = m.speed_bps
    print(f"  speed: {speed/1024:.0f} KB/s (expect ~1000)")
    assert 500_000 < speed < 1_500_000, f"速度应在 500KB-1.5MB/s 范围, 实际 {speed}"

    time.sleep(0.5)
    m.update(2_000_000)  # another 1.5MB in 0.5s
    speed2 = m.speed_bps
    print(f"  speed: {speed2/1024:.0f} KB/s")
    assert speed2 > 0
    print(f"  ✓ 基本计算正常")

    # ── 2. Window pruning ──
    print("\n── 2. 窗口裁剪 ──")
    m2 = SpeedMeter(window_seconds=0.5)
    m2.update(100)
    time.sleep(0.6)  # > window
    m2.update(200)
    # Only 1 sample in window → speed = 0
    assert m2.speed_bps == 0.0, f"单样本速度应为 0, 实际 {m2.speed_bps}"
    print(f"  ✓ 旧样本正确被裁剪")

    # ── 3. ETA ──
    print("\n── 3. ETA 估算 ──")
    m3 = SpeedMeter(window_seconds=5.0)
    m3.update(0)
    time.sleep(0.5)
    m3.update(1_000_000)
    eta = m3.eta_seconds(1_000_000, 10_000_000)
    print(f"  downloaded: 1MB/10MB, ETA: {eta:.1f}s")
    assert eta is not None and eta > 0
    assert m3.eta_seconds(10_000_000, 10_000_000) == 0.0
    assert m3.eta_seconds(0, 0) == 0.0
    print(f"  ✓ ETA 计算正常")

    # ── 4. Pause / resume ──
    print("\n── 4. 暂停/恢复 ──")
    m4 = SpeedMeter(window_seconds=5.0)
    m4.update(0)
    time.sleep(0.3)
    m4.update(500_000)
    assert m4.speed_bps > 0
    m4.pause()
    assert m4.speed_bps == 0.0, "暂停后速度应为 0"
    m4.update(1_000_000)  # should be ignored while paused
    assert m4.speed_bps == 0.0
    m4.resume()
    m4.update(2_000_000)
    time.sleep(0.3)
    m4.update(2_500_000)
    assert m4.speed_bps > 0
    print(f"  ✓ 暂停/恢复正确")

    # ── 5. SpeedTracker multi-level ──
    print("\n── 5. SpeedTracker 多级聚合 ──")
    st = SpeedTracker(window_seconds=5.0)
    st.update("RJ001", "t1", 0)
    time.sleep(0.3)
    st.update("RJ001", "t1", 500_000)

    t_speed = st.track_speed("RJ001", "t1")
    w_speed = st.work_speed("RJ001")
    g_speed = st.global_speed()
    print(f"  track: {t_speed/1024:.0f} KB/s")
    print(f"  work:  {w_speed/1024:.0f} KB/s")
    print(f"  global:{g_speed/1024:.0f} KB/s")
    assert t_speed > 0 and w_speed > 0 and g_speed > 0

    # Pause work
    st.pause_work("RJ001")
    assert st.track_speed("RJ001", "t1") == 0.0
    assert st.work_speed("RJ001") == 0.0

    # Add another track
    st.update("RJ001", "t2", 0)
    time.sleep(0.3)
    st.update("RJ001", "t2", 300_000)
    # Still paused so speed should be 0
    assert st.track_speed("RJ001", "t2") == 0.0
    print(f"  ✓ SpeedTracker 多级聚合正确")

    # ── 6. Reset ──
    print("\n── 6. Reset ──")
    m5 = SpeedMeter()
    m5.update(0)
    time.sleep(0.3)
    m5.update(500_000)
    assert m5.speed_bps > 0
    m5.reset()
    assert m5.speed_bps == 0.0
    assert len(m5._samples) == 0
    print(f"  ✓ Reset 正确")

    print(f"\n{'='*60}")
    print(f"  ✓ SpeedMeter 测试通过")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
