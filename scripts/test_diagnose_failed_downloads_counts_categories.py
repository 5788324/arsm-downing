#!/usr/bin/env python3
"""diagnose_failed_downloads 统计所有分类."""
import asyncio, sys, os; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  diagnose counts categories\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault
    cfg=ConfigManager.load(); db=LibraryVault()
    rj="RJ99937"; d=f"/tmp/{rj}"; os.makedirs(d,exist_ok=True)
    # partial file
    Path(f"{d}/t1.mp3.part").write_bytes(b"x"*50)
    db.upsert_download(f"{rj}:t1",rj,"t1",f"{d}/t1.mp3","failed",50,100,error="ConnectionError: timeout")
    db.commit()

    diag=db.diagnose_failed_downloads()
    for k in ("failed_total","failed_resumable_partial_file","failed_retry_from_zero","failed_missing_file","failed_missing_url_or_metadata","failed_complete_but_db_failed","paused_resumable","paused_missing_file","registered_count","per_error_prefix","per_root_path"):
        assert k in diag,f"missing key: {k}"
        print(f"  {k}: {diag[k]}" if not isinstance(diag[k],dict) else f"  {k}: {len(diag[k])} entries")
    print(f"  ✓ all categories present")

    Path(f"{d}/t1.mp3.part").unlink(); os.rmdir(d)
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,)); db.commit()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
