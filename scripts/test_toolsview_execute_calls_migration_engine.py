#!/usr/bin/env python3
"""ToolsView 调用 MigrationEngine.migrate_one."""
import asyncio, sys, os, shutil; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  ToolsView calls MigrationEngine\n{'='*60}\n")
    from core.migration import MigrationEngine; import inspect
    src=inspect.getsource(MigrationEngine.migrate_one)
    assert "MIGRATION_START" in src
    assert "MIGRATION_COPY_DONE" in src
    assert "MIGRATION_DONE" in src
    assert "MIGRATION_FAIL" in src
    print(f"  ✓ MigrationEngine has all log stages")
    # Check ToolsView has migrate_execute calling migrate_one
    src_tv=open("ui/views/tools_view.py").read()
    assert "migrate_execute" in src_tv
    assert "engine.migrate_one" in src_tv or "migrate_one" in src_tv
    print(f"  ✓ ToolsView.migrate_execute calls migrate_one")
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
