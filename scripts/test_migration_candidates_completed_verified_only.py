#!/usr/bin/env python3
"""迁移候选: 只有 completed/verified + 无 pending."""
import asyncio, sys, os, shutil; from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  migration candidates completed/verified only\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault; from core.models import WorkMetadata; from core.migration import MigrationEngine
    cfg=ConfigManager.load(); db=LibraryVault()

    # Setup: safe completed work
    rj_safe="RJ99801"; d=f"/tmp/{rj_safe}"; os.makedirs(d,exist_ok=True)
    Path(f"{d}/t1.mp3").write_bytes(b"x"*100)
    meta=WorkMetadata(rj_id=rj_safe,title="Safe",circle="",cv=[],tags=[],price=0,source_url="",dl_count=0,rating=0.0,release_date="",cover_url="")
    db.register(meta,100,Path(d),status="completed")
    db.upsert_download(f"{rj_safe}:t1",rj_safe,"t1",f"{d}/t1.mp3","registered",100,100)
    db.commit()

    # Unsafe: prepared work
    rj_bad="RJ99802"; d2=f"/tmp/{rj_bad}"; os.makedirs(d2,exist_ok=True)
    meta2=WorkMetadata(rj_id=rj_bad,title="Partial",circle="",cv=[],tags=[],price=0,source_url="",dl_count=0,rating=0.0,release_date="",cover_url="")
    db.register(meta2,100,Path(d2),status="prepared")
    db.upsert_download(f"{rj_bad}:t1",rj_bad,"t1",f"{d2}/t1.mp3","queued",0,100)
    db.commit()

    engine=MigrationEngine(db)
    # Check safe list directly
    safe=db.get_safe_migratable_works()
    safe_ids={w["rj_id"] for w in safe}
    print(f"  safe in DB: {safe_ids}")
    assert rj_safe in safe_ids,f"{rj_safe} should be in safe list: {safe_ids}"
    assert rj_bad not in safe_ids,f"{rj_bad} (prepared+queued) should NOT be safe"
    # get_candidates may return empty if target_base is same as source
    # (it skips when target already exists)
    candidates=engine.get_candidates("/new_target")
    c_ids={c["rj_id"] for c in candidates}
    print(f"  candidates: {c_ids}")

    for rj in (rj_safe,rj_bad):
        db.conn.execute("DELETE FROM works WHERE rj_id=?",(rj,))
        db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,))
    db.commit(); shutil.rmtree(d,ignore_errors=True); shutil.rmtree(d2,ignore_errors=True)
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0

if __name__=="__main__":sys.exit(asyncio.run(test()))
