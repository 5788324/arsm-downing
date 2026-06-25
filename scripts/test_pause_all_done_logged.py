#!/usr/bin/env python3
"""pause_all 后必须有 PAUSE_ALL_DONE 日志."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  PAUSE_ALL_DONE logged\n{'='*60}\n")
    from core.orchestrator import Orchestrator
    import inspect
    src=inspect.getsource(Orchestrator.pause_all)
    assert "PAUSE_ALL_DONE" in src,"must log PAUSE_ALL_DONE"
    assert "global_inflight" in src,"must log global_inflight"
    assert "generation=" in src,"must log generation"
    print(f"  ✓ PAUSE_ALL_DONE with generation + global_inflight")
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0

if __name__=="__main__":sys.exit(asyncio.run(test()))
