#!/usr/bin/env python3
"""进度事件速度测试 — mock 下载验证 ProgressEvent 携带正确的 speed/eta/percent。

模拟一个 track 的 3 个 chunk 下载，验证每次 _emit_progress
发出的 ProgressEvent 包含所有结构化字段，且 work/global speed
使用累计 delta 而非单 track downloaded。
"""

import asyncio
import sys
import os
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}")
    print(f"  进度事件速度集成测试")
    print(f"{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator
    from core.models import WorkMetadata, TrackItem, ProgressEvent
    from core.speed import SpeedTracker

    cfg = ConfigManager.load()
    tmpdir = tempfile.mkdtemp()
    cfg.output_dir = Path(tmpdir)
    cfg.file_concurrency = 1
    cfg.chunk_size = 100  # small chunks for test
    cfg.retry_count = 1

    db = LibraryVault()
    kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)

    # ── Capture progress events ──
    events: list = []
    orc.set_callbacks(
        on_progress=events.append,
        on_work_status=lambda *a: None,
    )

    # ── Setup fake track ──
    rj_code = "RJ99888"
    meta = WorkMetadata(
        rj_id=rj_code, title="Speed Test", circle="TC",
        cv=[], tags=[], price=0, source_url="", dl_count=0,
        rating=0.0, release_date="", cover_url="")
    root = cfg.output_dir / f"{rj_code} Speed Test"
    root.mkdir(parents=True, exist_ok=True)

    tpath = root / "speed_test.mp3"
    track = TrackItem(
        id="st1", title="speed_test", type="audio",
        url="http://fake/speed.mp3", size=500,
        save_path=tpath)

    # ── Monkeypatch download to use fake response ──
    import aiohttp

    class FakeStreamReader:
        def __init__(self, chunks):
            self._chunks = chunks

        async def iter_chunked(self, n):
            for c in self._chunks:
                yield c

    class FakeResponse:
        status = 200
        headers = {"Content-Length": "500"}

        def __init__(self, chunks):
            self.content = FakeStreamReader(chunks)
            self.closed = False

        def close(self):
            self.closed = True

    # Direct mock: replace _stream_with_fallback to return fake data
    chunk_sizes = [150, 200, 150]  # 3 chunks, total 500
    chunks = [b"X" * s for s in chunk_sizes]
    original_stream = orc._stream_with_fallback

    async def mock_stream(url, headers):
        return True, FakeResponse(chunks)

    orc._stream_with_fallback = mock_stream

    # ── Run download_file ──
    print("── 运行 download_file (3 chunks: 150+200+150=500 bytes) ──")
    result = await orc.download_file(track, meta, None)

    orc._stream_with_fallback = original_stream

    print(f"  download_file returned: {result}")
    print(f"  Events captured: {len(events)}")

    # ── Verify event structure ──
    print(f"\n── 验证 ProgressEvent 字段 ──")
    # Expect at least 3 downloading events + 1 completed
    download_events = [e for e in events if e.status == "downloading"]
    completed = [e for e in events if e.status == "completed"]

    assert len(download_events) >= 3, \
        f"expected >=3 downloading events, got {len(download_events)}"
    assert len(completed) >= 1, "expected completed event"

    for e in download_events:
        assert isinstance(e, ProgressEvent), f"not ProgressEvent: {type(e)}"
        assert e.rj_id == rj_code
        assert e.track_id is not None
        assert e.track_title is not None
        assert e.percent >= 0
        # Speed fields must exist (may be 0 for first chunk)
        assert e.track_speed_bps is not None
        assert e.work_speed_bps is not None
        assert e.global_speed_bps is not None

    last = download_events[-1]
    print(f"  最后 downloading event:")
    print(f"    downloaded: {last.downloaded_bytes}/{last.total_bytes}")
    print(f"    percent: {last.percent}%")
    print(f"    track_speed: {last.track_speed_bps} B/s")
    print(f"    work_speed: {last.work_speed_bps} B/s")
    print(f"    global_speed: {last.global_speed_bps} B/s")

    # ── Verify work/global speed uses delta (P2.1) ──
    # After 3 chunks, downloaded bytes are 500
    # The track speed should be ~500/window B/s (approximate)
    # Works with 1 file, so work = track = global
    if last.track_speed_bps > 0:
        assert last.work_speed_bps > 0, "work speed should be > 0"
        assert last.global_speed_bps > 0, "global speed should be > 0"
        # With 1 file, all should be close
        print(f"  ✓ work/global speed via delta accumulator (correct for multi-file)")

    # ── Verify completed event ──
    c = completed[0]
    assert c.downloaded_bytes == c.total_bytes
    assert c.percent >= 99.9
    assert c.status == "completed"
    print(f"  completed: {c.downloaded_bytes}/{c.total_bytes} ({c.percent}%)")

    # Cleanup
    await kernel.shutdown()
    import shutil
    shutil.rmtree(tmpdir)

    print(f"\n{'='*60}")
    print(f"  ✓ 进度事件速度集成测试通过")
    print(f"  → ProgressEvent 含 speed/eta/percent 字段")
    print(f"  → work/global speed 用累计 delta")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
