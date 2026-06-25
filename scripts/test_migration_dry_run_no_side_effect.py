#!/usr/bin/env python3
"""dry-run 无副作用 — 不修改 DB 不移动文件."""
import asyncio, sys, os, shutil; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  dry-run no side effect\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault; from core.models import WorkMetadata; from core.migration import MigrationEngine
    cfg=ConfigManager.load(); db=LibraryVault()
    rj="RJ99805"; d=f"/tmp/{rj}"; os.makedirs(d,exist_ok=True)
    Path(f"{d}/t1.mp3").write_bytes(b"x"*100)
    meta=WorkMetadata(rj_id=rj,title="T",circle="",cv=[],tags=[],price=0,source_url="",dl_count=0,rating=0.0,release_date="",cover_url="")
    db.register(meta,100,Path(d),status="completed"); db.commit()
    ws_before=db.conn.execute("SELECT local_path FROM works WHERE rj_id=?",(rj,)).fetchone()["local_path"]
    engine=MigrationEngine(db); dry=engine.dry_run("/new")
    assert dry["candidate_count"]>=1
    ws_after=db.conn.execute("SELECT local_path FROM works WHERE rj_id=?",(rj,)).fetchone()["local_path"]
    assert ws_before==ws_after,"dry-run must not modify DB"
    assert os.path.exists(d),"dry-run must not move files"
    print(f"  ✓ DB unchanged, files in place")
    db.conn.execute("DELETE FROM works WHERE rj_id=?",(rj,)); db.commit(); shutil.rmtree(d,ignore_errors=True)
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
