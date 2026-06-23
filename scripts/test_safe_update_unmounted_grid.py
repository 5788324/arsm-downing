#!/usr/bin/env python3
"""safe_update 未挂载测试 — grid 不在 page 时不抛异常."""
import asyncio, sys; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  safe_update 未挂载测试\n{'='*60}\n")
    from ui.views.library_view import LibraryView, safe_update
    class FA:db=type('o',(),{'search':lambda q:[]})()
    v=LibraryView.__new__(LibraryView);v.app_controller=FA()
    v.__init__(FA())
    # grid is not on page — safe_update should not crash
    try:
        safe_update(v.grid)
        print("  ✓ safe_update 不抛异常")
    except AssertionError as e:
        print(f"  ✗ {e}");return 1
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
