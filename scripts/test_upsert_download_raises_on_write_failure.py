#!/usr/bin/env python3
"""upsert_download 写失败 raise 测试."""
import asyncio, sys, sqlite3; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  upsert_download 写失败 raise 测试\n{'='*60}\n")
    from core.database import LibraryVault
    db=LibraryVault()
    db.conn.execute("DROP TABLE IF EXISTS downloads");db.conn.commit()
    try:
        db.upsert_download("id","rj","t","/tmp","queued")
        print("  ✗ 应该 raise 但没有")
        return 1
    except sqlite3.Error as e:
        print(f"  ✓ raise sqlite3.Error: {e}")
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
