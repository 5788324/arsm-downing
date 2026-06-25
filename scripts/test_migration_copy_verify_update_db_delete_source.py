#!/usr/bin/env python3
"""迁移端到端: copy→verify→db_update→delete_source."""
import asyncio, sys, os, shutil; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  migration copy verify db delete\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault; from core.models import WorkMetadata; from core.migration import MigrationEngine
    cfg=ConfigManager.load(); db=LibraryVault()

    rj="RJ99806"; src=f"/tmp/{rj}"; tgt=f"/tmp/{rj}_migrated"
    os.makedirs(src,exist_ok=True)
    Path(f"{src}/t1.mp3").write_bytes(b"x"*100)
    meta=WorkMetadata(rj_id=rj,title="T",circle="",cv=[],tags=[],price=0,source_url="",dl_count=0,rating=0.0,release_date="",cover_url="")
    db.register(meta,100,Path(src),status="completed")
    db.upsert_download(f"{rj}:t1",rj,"t1",f"{src}/t1.mp3","registered",100,100)
    db.commit()

    engine=MigrationEngine(db); res=engine.migrate_one(rj,src,tgt)
    print(f"  result: {res}")
    assert res["success"],f"migration failed: {res}"
    # Verify: source gone, target exists
    assert not os.path.exists(src),"source should be deleted"
    assert os.path.exists(tgt),"target should exist"
    # Verify DB updated
    ws=db.conn.execute("SELECT local_path FROM works WHERE rj_id=?",(rj,)).fetchone()["local_path"]
    assert ws==tgt,f"works.local_path should be {tgt}, got {ws}"
    print(f"  ✓ source deleted, target exists, DB updated: {ws}")

    shutil.rmtree(tgt,ignore_errors=True)
    db.conn.execute("DELETE FROM works WHERE rj_id=?",(rj,))
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,)); db.commit()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
