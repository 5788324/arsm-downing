#!/usr/bin/env python3
"""dry_run 返回完整候选列表（支持小批量选择）."""
import asyncio, sys, os, shutil; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  migration small batch limit\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault; from core.models import WorkMetadata; from core.migration import MigrationEngine
    cfg=ConfigManager.load(); db=LibraryVault()
    rjs=[]
    for i in range(5):
        rj=f"RJ{99820000+i:08d}"; rjs.append(rj); d=f"/tmp/{rj}"; os.makedirs(d,exist_ok=True)
        Path(f"{d}/t1.mp3").write_bytes(b"x"*10)
        meta=WorkMetadata(rj_id=rj,title=f"T{i}",circle="",cv=[],tags=[],price=0,source_url="",dl_count=0,rating=0.0,release_date="",cover_url="")
        db.register(meta,10,Path(d),status="completed"); db.commit()
    engine=MigrationEngine(db); dry=engine.dry_run("/new")
    assert dry["candidate_count"]>=5,f"should have >=5 candidates"
    # Small batch: pick 3
    small=dry["candidates"][:3]
    assert len(small)==3
    print(f"  ✓ {len(dry['candidates'])} candidates, small batch: {len(small)}")
    for rj in rjs:
        shutil.rmtree(f"/tmp/{rj}",ignore_errors=True)
        db.conn.execute("DELETE FROM works WHERE rj_id=?",(rj,))
    db.commit()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
