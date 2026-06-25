#!/usr/bin/env python3
"""resume_all 打印 RESUME_ALL_SCAN 分类 counts."""
import asyncio, sys; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  RESUME_ALL_SCAN logged\n{'='*60}\n")
    from core.orchestrator import Orchestrator; import inspect
    src=inspect.getsource(Orchestrator.resume_all)
    assert "RESUME_ALL_SCAN" in src,"must log RESUME_ALL_SCAN"
    assert "RESUME_ALL_ENQUEUED" in src,"must log RESUME_ALL_ENQUEUED"
    print(f"  ✓ RESUME_ALL_SCAN + RESUME_ALL_ENQUEUED in source")
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
