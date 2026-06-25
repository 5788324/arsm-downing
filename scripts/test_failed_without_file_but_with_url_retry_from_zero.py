#!/usr/bin/env python3
"""failed 无文件但有 metadata → retry_from_zero."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  failed without file retry from zero\n{'='*60}\n")
    from core.config import ConfigManager
    from core.database import LibraryVault
    cfg=ConfigManager.load(); db=LibraryVault()

    rj="RJ99932"
    db.upsert_download(f"{rj}:t1",rj,"t1",f"/tmp/{rj}/t1.mp3","failed",0,100)
    db.set_metadata_cache(rj,"T","C","",{"title":"T"},[{"type":"audio","title":"t1","id":"1","mediaDownloadUrl":"http://localhost/t1.mp3","size":100}])
    db.commit()

    diag=db.diagnose_failed_downloads()
    assert diag["failed_retry_from_zero"]>=1,f"should be retryable from zero: {diag}"
    print(f"  ✓ failed_retry_from_zero={diag['failed_retry_from_zero']}")

    db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,))
    db.conn.execute("DELETE FROM metadata_cache WHERE rj_id=?",(rj,))
    db.commit()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0

if __name__=="__main__":sys.exit(asyncio.run(test()))
