#!/usr/bin/env python3
"""迁移执行需要候选过滤 — confirmation safety check."""
import asyncio, sys; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  migration requires candidate filter\n{'='*60}\n")
    from core.migration import MigrationEngine; from core.config import ConfigManager; from core.database import LibraryVault
    cfg=ConfigManager.load(); db=LibraryVault()
    engine=MigrationEngine(db)
    # Without any safe works, candidates should be empty
    dry=engine.dry_run("/nonexistent")
    assert dry["candidate_count"]==0,"no candidates with empty DB"
    print(f"  ✓ empty DB → 0 candidates (safety OK)")
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
