#!/usr/bin/env python3
"""迁移不碰 active/queued RJ."""
import asyncio, sys, os, shutil; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  migration does not touch active/queued\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault; from core.models import WorkMetadata; from core.migration import MigrationEngine
    cfg=ConfigManager.load(); db=LibraryVault()
    rj="RJ99813"; d=f"/tmp/{rj}"; os.makedirs(d,exist_ok=True)
    Path(f"{d}/t1.mp3").write_bytes(b"x"*100)
    meta=WorkMetadata(rj_id=rj,title="T",circle="",cv=[],tags=[],price=0,source_url="",dl_count=0,rating=0.0,release_date="",cover_url="")
    db.register(meta,100,Path(d),status="completed")
    db.upsert_download(f"{rj}:t1",rj,"t1",f"{d}/t1.mp3","registered",100,100)
    db.commit()
    engine=MigrationEngine(db)
    # This should be safe
    safe=db.get_safe_migratable_works()
    assert any(w["rj_id"]==rj for w in safe),f"{rj} should be safe"
    # Now add a pending download
    db.upsert_download(f"{rj}:t2",rj,"t2",f"{d}/t2.mp3","queued",0,100); db.commit()
    safe2=db.get_safe_migratable_works()
    assert not any(w["rj_id"]==rj for w in safe2),f"{rj} with pending should NOT be safe"
    print(f"  ✓ safe→unsafe when queued download is added")
    shutil.rmtree(d,ignore_errors=True)
    db.conn.execute("DELETE FROM works WHERE rj_id=?",(rj,)); db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,)); db.commit()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
