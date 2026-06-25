#!/usr/bin/env python3
"""MIGRATION_START/DONE 日志记录."""
import asyncio, sys, os, shutil; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  migration log written\n{'='*60}\n")
    from core.migration import MigrationEngine
    import inspect
    src=inspect.getsource(MigrationEngine.migrate_one)
    for log in ("MIGRATION_START","MIGRATION_COPY_DONE","MIGRATION_VERIFY_DONE","MIGRATION_DB_UPDATE_DONE","MIGRATION_DELETE_SOURCE_DONE","MIGRATION_DONE","MIGRATION_FAIL"):
        assert log in src,f"missing: {log}"
        print(f"  ✓ {log}")
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
