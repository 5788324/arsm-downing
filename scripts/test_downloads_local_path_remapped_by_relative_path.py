#!/usr/bin/env python3
"""迁移后 downloads.local_path 按相对路径重映射."""
import asyncio, sys, os, shutil; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  downloads path remapped\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault; from core.models import WorkMetadata; from core.migration import MigrationEngine
    cfg=ConfigManager.load(); db=LibraryVault()
    rj="RJ99810"; src=f"/tmp/{rj}"; tgt=f"/tmp/{rj}_remap"; os.makedirs(f"{src}/sub",exist_ok=True)
    Path(f"{src}/t1.mp3").write_bytes(b"x"*100); Path(f"{src}/sub/t2.mp3").write_bytes(b"x"*200)
    meta=WorkMetadata(rj_id=rj,title="T",circle="",cv=[],tags=[],price=0,source_url="",dl_count=0,rating=0.0,release_date="",cover_url="")
    db.register(meta,300,Path(src),status="completed")
    db.upsert_download(f"{rj}:t1",rj,"t1",f"{src}/t1.mp3","registered",100,100)
    db.upsert_download(f"{rj}:t2",rj,"t2",f"{src}/sub/t2.mp3","registered",200,200)
    db.commit()
    engine=MigrationEngine(db); res=engine.migrate_one(rj,src,tgt)
    assert res["success"],f"failed: {res}"
    for row in db.conn.execute("SELECT local_path FROM downloads WHERE rj_id=?",(rj,)):
        assert row["local_path"].startswith(tgt),f"should start with {tgt}: {row['local_path']}"
        print(f"  ✓ {row['local_path']}")
    shutil.rmtree(tgt,ignore_errors=True)
    db.conn.execute("DELETE FROM works WHERE rj_id=?",(rj,)); db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,)); db.commit()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
