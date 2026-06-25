#!/usr/bin/env python3
"""registered tracks for completed works → 不自动入队."""
import asyncio, sys; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  registered tracks not auto started\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault; from core.models import WorkMetadata
    cfg=ConfigManager.load(); db=LibraryVault()
    rj="RJ99936"
    meta=WorkMetadata(rj_id=rj,title="Done",circle="",cv=[],tags=[],price=0,source_url="",dl_count=0,rating=0.0,release_date="",cover_url="")
    db.register(meta,1000,Path(f"/tmp/{rj}"),status="completed")
    db.upsert_download(f"{rj}:t1",rj,"t1",f"/tmp/{rj}/t1.mp3","registered",100,100)
    db.commit()
    pending=db.get_pending_rj_ids()
    assert rj not in pending,f"completed work should NOT be in pending: {pending}"
    print(f"  ✓ registered+completed → not in pending_rj_ids")
    db.conn.execute("DELETE FROM works WHERE rj_id=?",(rj,))
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,)); db.commit()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
