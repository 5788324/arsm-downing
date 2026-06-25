#!/usr/bin/env python3
"""迁移拒绝 pending downloads — queued/paused 不入候选."""
import asyncio, sys, os, shutil; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  migration rejects pending\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault; from core.models import WorkMetadata; from core.migration import MigrationEngine
    cfg=ConfigManager.load(); db=LibraryVault()
    rj="RJ99803"; d=f"/tmp/{rj}"; os.makedirs(d,exist_ok=True)
    Path(f"{d}/t1.mp3").write_bytes(b"x"*100)
    meta=WorkMetadata(rj_id=rj,title="P",circle="",cv=[],tags=[],price=0,source_url="",dl_count=0,rating=0.0,release_date="",cover_url="")
    db.register(meta,100,Path(d),status="completed")
    db.upsert_download(f"{rj}:t1",rj,"t1",f"{d}/t1.mp3","paused",50,100)
    db.commit()
    engine=MigrationEngine(db); cand=engine.get_candidates("/tmp")
    assert rj not in {c["rj_id"] for c in cand},f"paused should be rejected"
    print(f"  ✓ paused rejected")
    db.conn.execute("DELETE FROM works WHERE rj_id=?",(rj,)); db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,))
    db.commit(); shutil.rmtree(d,ignore_errors=True)
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
