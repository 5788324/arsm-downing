#!/usr/bin/env python3
"""验证检测缺失的下载文件."""
import asyncio, sys, os, shutil; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  verify detects missing download file\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault; from core.models import WorkMetadata
    cfg=ConfigManager.load(); db=LibraryVault()
    rj="RJ99969"; d=f"/tmp/{rj}"; os.makedirs(d,exist_ok=True)
    meta=WorkMetadata(rj_id=rj,title="T",circle="",cv=[],tags=[],price=0,source_url="",dl_count=0,rating=0.0,release_date="",cover_url="")
    db.register(meta,100,Path(d),status="verified")
    db.upsert_download(f"{rj}:t1",rj,"t1",f"{d}/t1.mp3","registered",100,100)  # no actual file
    db.commit()
    exists=os.path.exists(f"{d}/t1.mp3")
    assert not exists,"file should not exist"
    print(f"  ✓ missing file detected: exists={exists}")
    shutil.rmtree(d,ignore_errors=True)
    db.conn.execute("DELETE FROM works WHERE rj_id=?",(rj,)); db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,)); db.commit()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
