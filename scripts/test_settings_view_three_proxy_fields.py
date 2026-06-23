#!/usr/bin/env python3
"""SettingsView 三代理字段 — 源码检查."""
import asyncio, sys; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  SettingsView 三代理字段检查\n{'='*60}\n")
    src = Path("ui/views/settings_view.py").read_text(encoding="utf-8")
    for name in ("metadata_proxy_input","cover_proxy_input","download_proxy_input"):
        assert name in src,f"源码缺 {name}"
    print("  ✓ 三个代理字段均存在于源码中")
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
