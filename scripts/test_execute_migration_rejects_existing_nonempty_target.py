#!/usr/bin/env python3
"""拒绝已有非空 target."""
import asyncio, sys, os, shutil; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  rejects existing nonempty target\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault; from core.models import WorkMetadata; from core.migration import MigrationEngine
    cfg=ConfigManager.load(); db=LibraryVault()
    rj="RJ99966"; src=f"/tmp/{rj}"; tgt=f"/tmp/{rj}_ex"; os.makedirs(src,exist_ok=True); os.makedirs(tgt,exist_ok=True)
    Path(f"{src}/t1.mp3").write_bytes(b"x"*100); Path(f"{tgt}/existing.txt").write_bytes(b"x")
    meta=WorkMetadata(rj_id=rj,title="T",circle="",cv=[],tags=[],price=0,source_url="",dl_count=0,rating=0.0,release_date="",cover_url="")
    db.register(meta,100,Path(src),status="completed"); db.commit()
    engine=MigrationEngine(db); candidates=engine.get_candidates("/tmp")
    my_cand=[c for c in candidates if c["rj_id"]==rj]
    assert len(my_cand)==0,f"should reject existing nonempty target: {my_cand}"
    print(f"  ✓ existing nonempty target → rejected")
    shutil.rmtree(src,ignore_errors=True); shutil.rmtree(tgt,ignore_errors=True)
    db.conn.execute("DELETE FROM works WHERE rj_id=?",(rj,)); db.commit()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
