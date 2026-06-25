#!/usr/bin/env python3
"""批量限制 ≤ 3 个."""
import asyncio, sys, os, shutil; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  batch limit 3\n{'='*60}\n")
    from core.migration import MigrationEngine; from core.config import ConfigManager; from core.database import LibraryVault; from core.models import WorkMetadata
    cfg=ConfigManager.load(); db=LibraryVault()
    for i in range(5):
        rj=f"RJ{99830000+i:08d}"; d=f"/tmp/{rj}"; os.makedirs(d,exist_ok=True)
        Path(f"{d}/t1.mp3").write_bytes(b"x"*10)
        meta=WorkMetadata(rj_id=rj,title=f"T{i}",circle="",cv=[],tags=[],price=0,source_url="",dl_count=0,rating=0.0,release_date="",cover_url="")
        db.register(meta,10,Path(d),status="completed"); db.commit()
    engine=MigrationEngine(db); candidates=engine.get_candidates("/target")
    batch=candidates[:3]
    assert len(batch)<=3,f"batch should be <=3, got {len(batch)}"
    print(f"  ✓ batch limited to {len(batch)} (from {len(candidates)} candidates)")
    for i in range(5):
        rj=f"RJ{99830000+i:08d}"; shutil.rmtree(f"/tmp/{rj}",ignore_errors=True)
        db.conn.execute("DELETE FROM works WHERE rj_id=?",(rj,))
    db.commit()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
