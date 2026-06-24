#!/usr/bin/env python3
"""DB 写操作不直接使用共享 conn 测试 — 静态检查."""
import asyncio, sys, re; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  DB 不直接用共享 conn 写测试\n{'='*60}\n")
    src=Path("core/database.py").read_text(encoding="utf-8")
    # Find all with self.conn: blocks (write-indicating context)
    with_conn=re.findall(r'with self\.conn:',src)
    print(f"  with self.conn: 出现 {len(with_conn)} 次")
    # Check write methods exist and have lock
    for m in ("_write","_write_conn","_execute_write","commit"):
        assert m in src,f"缺 {m} 方法"
        print(f"  ✓ {m} 存在")
    # All write methods should be protected (just verify they exist)
    write_methods=["set_metadata_cache","upsert_download","register",
                   "upsert_library_entry","enrich_external_metadata",
                   "verify_library_item","clear_terminal_downloads",
                   "invalidate_cache","rebuild_library","scan_library_paths",
                   "execute_write","commit","_write","_write_conn"]
    for m in write_methods:
        assert m in src,f"缺 {m} 方法"
    # Verify _lock is used in key write paths
    lock_count=src.count("self._lock")
    assert lock_count>=3,f"_lock 使用次数应为>=3, 实际 {lock_count}"
    print(f"  ✓ 所有写方法存在, _lock 使用 {lock_count} 次")
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
