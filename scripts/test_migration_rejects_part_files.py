#!/usr/bin/env python3
"""迁移拒绝 .part 文件 — get_candidates 排除含.part的作品."""
import asyncio, sys, os, shutil; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  migration rejects part files\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault; from core.models import WorkMetadata; from core.migration import MigrationEngine
    cfg=ConfigManager.load(); db=LibraryVault()
    rj="RJ99804"; d=f"/tmp/{rj}"; os.makedirs(d,exist_ok=True)
    Path(f"{d}/t1.mp3").write_bytes(b"x"*100); Path(f"{d}/t1.mp3.part").write_bytes(b"x")
    meta=WorkMetadata(rj_id=rj,title="P",circle="",cv=[],tags=[],price=0,source_url="",dl_count=0,rating=0.0,release_date="",cover_url="")
    db.register(meta,100,Path(d),status="completed"); db.commit()
    engine=MigrationEngine(db); cand=engine.get_candidates("/tmp")
    print(f"  candidates: {len(cand)}")
    assert rj not in {c["rj_id"] for c in cand},f"has .part should be rejected"
    print(f"  ✓ .part rejected")
    db.conn.execute("DELETE FROM works WHERE rj_id=?",(rj,)); db.commit(); shutil.rmtree(d,ignore_errors=True)
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
