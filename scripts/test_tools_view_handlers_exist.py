#!/usr/bin/env python3
"""ToolsView handler 存在性测试 — 所有按钮 on_click 方法必须存在."""
import asyncio, sys, re; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  ToolsView handler 存在性测试\n{'='*60}\n")
    src = Path("ui/views/tools_view.py").read_text(encoding="utf-8")
    # Find all on_click=self.xxx references
    handlers = set(re.findall(r'on_click=self\.(\w+)', src))
    # Find all method definitions
    methods = set(re.findall(r'def (\w+)\(self', src))
    missing = handlers - methods
    if missing:
        print(f"  ✗ 缺少方法: {missing}")
        return 1
    print(f"  ✓ {len(handlers)} 个 handler 全部存在: {sorted(handlers)}")
    assert "repair_db" in methods, "repair_db 缺失!"
    assert "clean_queue" in methods, "clean_queue 缺失!"
    assert "clear_cache" in methods, "clear_cache 缺失!"
    assert "test_network" in methods, "test_network 缺失!"
    assert "scan_library" in methods, "scan_library 缺失!"
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
