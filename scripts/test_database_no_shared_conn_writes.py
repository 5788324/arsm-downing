#!/usr/bin/env python3
"""DB 写方法不使用共享 conn 测试 — 静态源码检查."""
import asyncio, sys, re; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  DB 不直接写共享 conn 测试\n{'='*60}\n")
    src=Path("core/database.py").read_text(encoding="utf-8")
    # Methods that should NOT contain self.conn.execute or self.conn.commit
    write_methods=["set_metadata_cache","invalidate_cache","upsert_download",
                   "clear_terminal_downloads","register","upsert_library_entry",
                   "rebuild_library","enrich_external_metadata","verify_library_item"]
    violations=[]
    for m in write_methods:
        # Extract method body
        pat=rf'def {m}\((.*?)(?=\n    def |\n    @|\n\nclass |\Z)'
        body_match=re.search(pat,src,re.DOTALL)
        if body_match:
            body=body_match.group(0)
            if 'self.conn.execute' in body and m not in ("rebuild_library",):
                violations.append(f"{m}: self.conn.execute")
            if 'self.conn.commit' in body:
                violations.append(f"{m}: self.conn.commit")
    if violations:
        for v in violations: print(f"  ✗ {v}")
        return 1
    # Verify the new pattern is used
    execute_write_count=len(re.findall(r'self\._execute_write\(',src))
    write_count=len(re.findall(r'self\._write\(',src))
    assert execute_write_count>=7,f"_execute_write 使用 {execute_write_count} 次"
    assert write_count>=2,f"_write 使用 {write_count} 次"
    print(f"  ✓ 0 个写方法使用共享 conn")
    print(f"  ✓ _execute_write 使用 {execute_write_count} 次, _write 使用 {write_count} 次")
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
