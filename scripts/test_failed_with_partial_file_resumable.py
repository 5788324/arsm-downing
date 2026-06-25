#!/usr/bin/env python3
"""failed + partial file → resumable (RC7.10 verify)."""
import asyncio, sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  failed with partial file resumable\n{'='*60}\n")
    from core.config import ConfigManager
    from core.database import LibraryVault
    cfg=ConfigManager.load(); db=LibraryVault()

    rj="RJ99931"; d=f"/tmp/{rj}"; os.makedirs(d,exist_ok=True)
    Path(f"{d}/t1.mp3.part").write_bytes(b"x"*50)
    db.upsert_download(f"{rj}:t1",rj,"t1",f"{d}/t1.mp3","failed",50,100)
    db.commit()

    diag=db.diagnose_failed_downloads()
    print(f"  failed_total={diag['failed_total']}")
    print(f"  failed_resumable_partial_file={diag['failed_resumable_partial_file']}")
    assert diag["failed_resumable_partial_file"]>=1, f"should have resumable partial: {diag}"
    print(f"  ✓ failed with .part → resumable")

    Path(f"{d}/t1.mp3.part").unlink(); os.rmdir(d)
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,)); db.commit()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0

if __name__=="__main__":sys.exit(asyncio.run(test()))
