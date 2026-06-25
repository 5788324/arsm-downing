#!/usr/bin/env python3
"""dry-run shows source and target."""
import asyncio, sys, os, shutil; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  dry-run shows source + target\n{'='*60}\n")
    from core.migration import MigrationEngine; from core.config import ConfigManager; from core.database import LibraryVault; from core.models import WorkMetadata
    cfg=ConfigManager.load(); db=LibraryVault()
    rj="RJ99951"; d=f"/tmp/{rj}"; os.makedirs(d,exist_ok=True)
    Path(f"{d}/t1.mp3").write_bytes(b"x"*100)
    meta=WorkMetadata(rj_id=rj,title="T",circle="",cv=[],tags=[],price=0,source_url="",dl_count=0,rating=0.0,release_date="",cover_url="")
    db.register(meta,100,Path(d),status="completed"); db.commit()
    engine=MigrationEngine(db); candidates=engine.get_candidates("/new_target")
    for c in candidates:
        assert "source" in c; assert "target" in c
        print(f"  ✓ {c['rj_id']}: source={c['source']} target={c['target']}")
    db.conn.execute("DELETE FROM works WHERE rj_id=?",(rj,)); db.commit(); shutil.rmtree(d,ignore_errors=True)
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
