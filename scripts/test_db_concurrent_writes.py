#!/usr/bin/env python3
"""并发写测试 — 20 个并发 upsert 不报 SQLite 错."""
import asyncio, sys, threading; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  并发写测试\n{'='*60}\n")
    from core.database import LibraryVault;db=LibraryVault()
    def writer(i):
        try:
            db.upsert_download(f"RJ99999:t{i}","RJ99999",f"t{i}",
                               f"/tmp/t{i}.mp3","queued",i*10,100)
        except Exception as e:
            return e
        return None
    threads=[threading.Thread(target=writer,args=(i,)) for i in range(20)]
    for t in threads:t.start()
    for t in threads:t.join()
    rows=db.get_downloads_by_rj("RJ99999")
    assert len(rows)==20,f"应有 20, 实际 {len(rows)}"
    print(f"  ✓ 并发 20 写全部成功")
    db.conn.execute("DELETE FROM downloads WHERE rj_id='RJ99999'");db.commit()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
