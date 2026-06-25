#!/usr/bin/env python3
"""完整文件但 DB 标记为 failed → 应标记为 complete_but_failed."""
import asyncio, sys, os; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  complete file but DB failed\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault
    cfg=ConfigManager.load(); db=LibraryVault()
    rj="RJ99938"; d=f"/tmp/{rj}"; os.makedirs(d,exist_ok=True)
    Path(f"{d}/t1.mp3").write_bytes(b"x"*100)  # complete file
    db.upsert_download(f"{rj}:t1",rj,"t1",f"{d}/t1.mp3","failed",100,100)
    db.commit()
    diag=db.diagnose_failed_downloads()
    assert diag["failed_complete_but_db_failed"]>=1,f"complete file should be detected: {diag}"
    print(f"  ✓ failed_complete_but_db_failed={diag['failed_complete_but_db_failed']}")
    Path(f"{d}/t1.mp3").unlink(); os.rmdir(d)
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,)); db.commit()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
