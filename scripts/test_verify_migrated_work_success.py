#!/usr/bin/env python3
"""验证迁移后路径完整性."""
import asyncio, sys, os, shutil; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  verify migrated work success\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault; from core.models import WorkMetadata; from core.migration import MigrationEngine
    cfg=ConfigManager.load(); db=LibraryVault()
    rj="RJ99968"; src=f"/tmp/{rj}"; tgt=f"/tmp/{rj}_ok"; os.makedirs(src,exist_ok=True)
    Path(f"{src}/t1.mp3").write_bytes(b"x"*100)
    meta=WorkMetadata(rj_id=rj,title="T",circle="",cv=[],tags=[],price=0,source_url="",dl_count=0,rating=0.0,release_date="",cover_url="")
    db.register(meta,100,Path(src),status="completed")
    db.upsert_download(f"{rj}:t1",rj,"t1",f"{src}/t1.mp3","registered",100,100); db.commit()
    engine=MigrationEngine(db); res=engine.migrate_one(rj,src,tgt)
    assert res["success"]
    # Verify
    ws=db.conn.execute("SELECT local_path FROM works WHERE rj_id=?",(rj,)).fetchone()
    assert os.path.exists(ws["local_path"]),"works.local_path should exist"
    for dl in db.conn.execute("SELECT local_path FROM downloads WHERE rj_id=?",(rj,)):
        assert os.path.exists(dl["local_path"]),f"download {dl['local_path']} should exist"
        assert dl["local_path"].startswith(tgt),f"should be under target"
        print(f"  ✓ {dl['local_path']}")
    print(f"  ✓ all paths verified")
    shutil.rmtree(tgt,ignore_errors=True)
    db.conn.execute("DELETE FROM works WHERE rj_id=?",(rj,)); db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,)); db.commit()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
