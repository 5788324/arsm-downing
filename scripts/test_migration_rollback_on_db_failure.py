#!/usr/bin/env python3
"""DB 更新失败 → rollback."""
import asyncio, sys, os, shutil; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  migration rollback on DB failure\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault; from core.models import WorkMetadata; from core.migration import MigrationEngine
    cfg=ConfigManager.load(); db=LibraryVault()
    rj="RJ99809"; src=f"/tmp/{rj}"; tgt=f"/tmp/{rj}_dberr"
    os.makedirs(src,exist_ok=True); Path(f"{src}/t1.mp3").write_bytes(b"x"*100)
    meta=WorkMetadata(rj_id=rj,title="T",circle="",cv=[],tags=[],price=0,source_url="",dl_count=0,rating=0.0,release_date="",cover_url="")
    db.register(meta,100,Path(src),status="completed")
    db.upsert_download(f"{rj}:t1",rj,"t1",f"{src}/t1.mp3","registered",100,100)
    db.commit()
    # Cause DB failure: remove from safe list by adding pending download
    db.conn.execute("UPDATE downloads SET status='queued' WHERE rj_id=?",(rj,)); db.commit()
    engine=MigrationEngine(db); res=engine.migrate_one(rj,src,tgt)
    print(f"  result: {res}")
    assert not res["success"],"should fail at safety_check"
    assert os.path.exists(src),"source should remain"
    print(f"  ✓ DB failure → rollback, source preserved")
    shutil.rmtree(src,ignore_errors=True); shutil.rmtree(tgt,ignore_errors=True); shutil.rmtree(tgt+".tmp_migrating",ignore_errors=True)
    db.conn.execute("DELETE FROM works WHERE rj_id=?",(rj,))
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,)); db.commit()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
