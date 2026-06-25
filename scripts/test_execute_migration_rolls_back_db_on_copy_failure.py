#!/usr/bin/env python3
"""copy 失败 rollback — source preserved."""
import asyncio, sys, os, shutil; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  execute rollback on copy failure\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault; from core.models import WorkMetadata; from core.migration import MigrationEngine
    cfg=ConfigManager.load(); db=LibraryVault()
    rj="RJ99964"; src=f"/tmp/{rj}"; tgt=f"/tmp/{rj}_m"; os.makedirs(src,exist_ok=True)
    Path(f"{src}/t1.mp3").write_bytes(b"x"*100)
    meta=WorkMetadata(rj_id=rj,title="T",circle="",cv=[],tags=[],price=0,source_url="",dl_count=0,rating=0.0,release_date="",cover_url="")
    db.register(meta,100,Path(src),status="completed"); db.commit()
    orig=MigrationEngine._copy_dir; MigrationEngine._copy_dir=lambda s,src,dst: (_ for _ in ()).throw(Exception("copy failed"))
    engine=MigrationEngine(db); res=engine.migrate_one(rj,src,tgt)
    MigrationEngine._copy_dir=orig
    assert not res["success"]; assert os.path.exists(src),"source preserved"
    print(f"  ✓ rollback: source={os.path.exists(src)}")
    shutil.rmtree(src,ignore_errors=True); shutil.rmtree(tgt,ignore_errors=True); shutil.rmtree(tgt+".tmp_migrating",ignore_errors=True)
    db.conn.execute("DELETE FROM works WHERE rj_id=?",(rj,)); db.commit()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
