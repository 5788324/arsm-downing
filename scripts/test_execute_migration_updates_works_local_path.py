#!/usr/bin/env python3
"""migrate updates works.local_path."""
import asyncio, sys, os, shutil; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  migrate updates works.local_path\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault; from core.models import WorkMetadata; from core.migration import MigrationEngine
    cfg=ConfigManager.load(); db=LibraryVault()
    rj="RJ99961"; src=f"/tmp/{rj}"; tgt=f"/tmp/{rj}_m"; os.makedirs(src,exist_ok=True)
    Path(f"{src}/t1.mp3").write_bytes(b"x"*100)
    meta=WorkMetadata(rj_id=rj,title="T",circle="",cv=[],tags=[],price=0,source_url="",dl_count=0,rating=0.0,release_date="",cover_url="")
    db.register(meta,100,Path(src),status="completed")
    db.upsert_download(f"{rj}:t1",rj,"t1",f"{src}/t1.mp3","registered",100,100); db.commit()
    engine=MigrationEngine(db); res=engine.migrate_one(rj,src,tgt)
    assert res["success"],f"failed: {res}"
    ws=db.conn.execute("SELECT local_path FROM works WHERE rj_id=?",(rj,)).fetchone()["local_path"]
    assert ws==tgt,f"works.local_path={ws}, expected {tgt}"
    print(f"  ✓ works.local_path={tgt}")
    shutil.rmtree(tgt,ignore_errors=True)
    db.conn.execute("DELETE FROM works WHERE rj_id=?",(rj,)); db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,)); db.commit()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
