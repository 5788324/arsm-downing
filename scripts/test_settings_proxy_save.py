#!/usr/bin/env python3
"""SettingsView proxy 保存测试."""
import asyncio, sys, json; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  Settings proxy 保存测试\n{'='*60}\n")
    from core.config import ConfigManager
    cfg=ConfigManager()
    cfg.metadata_proxy="http://127.0.0.1:7897"; cfg.cover_proxy="http://127.0.0.1:7897"
    cfg.download_proxy=None; cfg.output_dir=Path("Downloads")
    cfg.save()
    with open("config.json") as f:d=json.load(f)
    assert d.get("metadata_proxy")=="http://127.0.0.1:7897"
    assert d.get("cover_proxy")=="http://127.0.0.1:7897"
    assert d.get("download_proxy") is None
    print(f"  ✓ metadata_proxy={d['metadata_proxy']}")
    print(f"  ✓ cover_proxy={d['cover_proxy']}")
    print(f"  ✓ download_proxy=None")
    # restore
    cfg.metadata_proxy=None;cfg.cover_proxy=None;cfg.save()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
