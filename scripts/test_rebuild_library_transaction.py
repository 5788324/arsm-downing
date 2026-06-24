#!/usr/bin/env python3
"""rebuild_library 事务测试 — 多步写入在同一 _write 中."""
import asyncio, sys, tempfile, shutil; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  rebuild_library 事务测试\n{'='*60}\n")
    from core.database import LibraryVault
    db=LibraryVault()
    tmp=tempfile.mkdtemp()
    (Path(tmp)/"RJ01603020 Test").mkdir()
    (Path(tmp)/"RJ01603020 Test"/"f.mp3").write_bytes(b"x"*100)
    result=db.rebuild_library([tmp])
    assert result["found"]==1
    assert result["indexed"]==1
    # Verify works entry was created within same transaction
    row=db.conn.execute("SELECT status FROM works WHERE rj_id='RJ01603020'").fetchone()
    assert row and row["status"]=="external"
    print(f"  ✓ found={result['found']} indexed={result['indexed']} status={row['status']}")
    db.conn.execute("DELETE FROM library_index");db.conn.execute("DELETE FROM works WHERE rj_id='RJ01603020'")
    db.commit();shutil.rmtree(tmp)
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
