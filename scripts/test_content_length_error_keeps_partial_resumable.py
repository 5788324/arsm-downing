#!/usr/bin/env python3
"""内容长度错误保留 partial 为 paused — 可 Range 续传."""
import asyncio, sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  content_length_error keeps partial resumable\n{'='*60}\n")
    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator
    from core.models import WorkMetadata, TrackItem

    cfg=ConfigManager.load()
    cfg.file_concurrency=1; cfg.retry_count=1
    db=LibraryVault(); kernel=NetworkKernel(cfg); orc=Orchestrator(kernel,cfg,db)

    rj="RJ99934"; d=f"/tmp/{rj}"; os.makedirs(d,exist_ok=True)
    part=Path(f"{d}/t1.mp3.part"); part.write_bytes(b"x"*50)

    meta=WorkMetadata(rj_id=rj,title="T",circle="",cv=[],tags=[],price=0,source_url="",dl_count=0,rating=0.0,release_date="",cover_url="")
    track=TrackItem(id="1",title="t1",type="audio",url="http://localhost/t1.mp3",size=100,save_path=Path(f"{d}/t1.mp3"))

    # Simulate content length error
    async def mock_corrupt_stream(url,headers):
        raise Exception("ContentLengthError: payload not completed")
    orc._stream_with_fallback=mock_corrupt_stream

    file_sem=asyncio.Semaphore(3)
    result=await orc.download_file(track,meta,None,file_sem)
    print(f"  download_file result: {result}")

    # Status should be paused (not failed) because partial file exists
    dl=db.get_downloads_summary(rj)
    print(f"  dl status: {dl}")
    assert dl.get("paused",0)>=1,f"partial+error → paused, not failed: {dl}"
    print(f"  ✓ partial file + error → paused (可续传)")

    part.unlink(); os.rmdir(d)
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,)); db.commit(); await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0

if __name__=="__main__":sys.exit(asyncio.run(test()))
