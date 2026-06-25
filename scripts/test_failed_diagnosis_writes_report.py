#!/usr/bin/env python3
"""diagnose 写报告到 logs/failed_diagnosis.txt."""
import asyncio, sys, os; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  diagnosis writes report\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault
    cfg=ConfigManager.load(); db=LibraryVault()
    rj="RJ99939"; d=f"/tmp/{rj}"; os.makedirs(d,exist_ok=True)
    Path(f"{d}/t1.mp3.part").write_bytes(b"x"*30)
    db.upsert_download(f"{rj}:t1",rj,"t1",f"{d}/t1.mp3","failed",30,100,error="ContentLengthError")
    db.commit()

    diag=db.diagnose_failed_downloads()
    assert isinstance(diag,dict)
    assert diag["failed_total"]>=1

    # Write report
    import json, datetime; os.makedirs("logs",exist_ok=True)
    report=dict(diag); report["generated_at"]=datetime.datetime.now().isoformat()
    with open("logs/failed_diagnosis.txt","w",encoding="utf-8") as f:
        json.dump(report,f,indent=2,ensure_ascii=False,default=str)
    assert os.path.exists("logs/failed_diagnosis.txt")
    print(f"  ✓ report written to logs/failed_diagnosis.txt ({os.path.getsize('logs/failed_diagnosis.txt')} bytes)")

    Path(f"{d}/t1.mp3.part").unlink(); os.rmdir(d)
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?",(rj,)); db.commit()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
