#!/usr/bin/env python3
"""UI 日志含 success/failure 阶段."""
import asyncio, sys; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  migration UI logs success and failure\n{'='*60}\n")
    src=open("ui/views/tools_view.py").read()
    for log in ("MIGRATION_START","MIGRATION_COPY_DONE","MIGRATION_VERIFY_DONE","MIGRATION_DB_UPDATE_DONE","MIGRATION_DELETE_SOURCE_DONE","MIGRATION_DONE","MIGRATION_FAIL"):
        assert log in src,f"UI missing log: {log}"
        print(f"  ✓ {log}")
    assert "verify_migrated" in src,"UI should have verify_migrated"
    print(f"  ✓ verify_migrated method exists")
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
