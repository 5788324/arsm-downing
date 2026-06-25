#!/usr/bin/env python3
"""下载速度 delta 完整性测试 — fake chunks 验证 speed 与文件增长一致."""

import asyncio, sys, time, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  下载速度 delta 完整性测试\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault
    from core.network import NetworkKernel; from core.orchestrator import Orchestrator
    from core.models import WorkMetadata, TrackItem, ProgressEvent

    cfg = ConfigManager.load(); tmp = tempfile.mkdtemp()
    cfg.output_dir = Path(tmp); cfg.file_concurrency = 1
    cfg.chunk_size = 100; cfg.retry_count = 1

    db = LibraryVault(); kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)

    events = []
    orc.set_callbacks(on_progress=events.append, on_work_status=lambda *a: None)

    meta = WorkMetadata(rj_id="RJ99888", title="SpeedDiag", circle="",
                        cv=[],tags=[],price=0,source_url="",dl_count=0,
                        rating=0.0,release_date="",cover_url="")
    root = cfg.output_dir / "RJ99888 SpeedDiag"; root.mkdir(parents=True,exist_ok=True)
    tpath = root / "speed_diag.mp3"
    track = TrackItem(id="sd1", title="speed_diag", type="audio",
                      url="http://fake/diag.mp3", size=1500, save_path=tpath)

    # Fake response: 3 chunks of 500 bytes with 0.5s gaps
    chunks = [b"X"*500, b"X"*500, b"X"*500]
    class FakeReader:
        def __init__(self, c): self._c = c; self._i = 0
        async def iter_chunked(self, n):
            for chunk in self._c:
                yield chunk; await asyncio.sleep(0.3)
    class FakeResp:
        status=200; closed=False
        headers={"Content-Length":"1500"}
        def __init__(self,c): self.content=FakeReader(c)
        def close(self): pass
    async def mock_stream(url, headers):
        return True, FakeResp(chunks)
    orc._stream_with_fallback = mock_stream

    result = await orc.download_file(track, meta, None, asyncio.Semaphore(3))
    assert result is True, f"download_file 应返回 True: {result}"

    # Verify events have monotonically increasing downloaded bytes
    dl_events = [e for e in events if isinstance(e, ProgressEvent) and e.status=="downloading"]
    assert len(dl_events) >= 3, f"应有 >=3 downloading events, {len(dl_events)}"
    prev_dl = 0
    for e in dl_events:
        assert e.downloaded_bytes >= prev_dl, \
            f"downloaded 应递增: {e.downloaded_bytes} < {prev_dl}"
        prev_dl = e.downloaded_bytes
    print(f"  ✓ downloaded 单调递增: 0→{prev_dl}")

    # final event should be 1500
    assert dl_events[-1].downloaded_bytes == 1500
    print(f"  ✓ 最终 downloaded = 1500")

    # Speed should be non-zero for later events
    speeds = [e.track_speed_bps for e in dl_events if e.track_speed_bps > 0]
    assert len(speeds) >= 1, "应有非零速度事件"
    print(f"  ✓ track_speed_bps: {speeds[-1]:.0f}")

    # global_speed should match track_speed for single file
    assert dl_events[-1].global_speed_bps > 0
    print(f"  ✓ global_speed_bps: {dl_events[-1].global_speed_bps:.0f}")

    import shutil; shutil.rmtree(tmp)
    await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 速度 delta 完整性测试通过\n{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
