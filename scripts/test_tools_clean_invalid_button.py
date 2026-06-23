#!/usr/bin/env python3
"""ToolsView 清理按钮 — 源码检查."""
import asyncio, sys; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  ToolsView 清理按钮检查\n{'='*60}\n")
    src = Path("ui/views/tools_view.py").read_text(encoding="utf-8")
    assert "clean_queue" in src,"源码缺 clean_queue"
    assert "清理无效队列" in src,"源码缺 清理无效队列"
    print("  ✓ clean_queue + 清理无效队列 均存在于源码中")
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
