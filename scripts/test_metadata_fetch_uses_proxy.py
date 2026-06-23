#!/usr/bin/env python3
"""fetch metadata 使用 proxy 测试."""
import asyncio, sys; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  fetch metadata proxy 测试\n{'='*60}\n")
    from core.config import ConfigManager
    cfg=ConfigManager()
    cfg.metadata_proxy="http://127.0.0.1:7897"; cfg.proxy=None
    assert cfg.get_proxy_for("metadata")=="http://127.0.0.1:7897"
    print(f"  ✓ metadata_proxy set → get_proxy_for('metadata')={cfg.get_proxy_for('metadata')}")
    cfg.metadata_proxy=None; cfg.proxy="http://127.0.0.1:7890"
    assert cfg.get_proxy_for("metadata")=="http://127.0.0.1:7890"
    print(f"  ✓ proxy fallback → {cfg.get_proxy_for('metadata')}")
    assert cfg.get_proxy_for("download") is None
    print(f"  ✓ download_proxy default=None (直连)")
    cfg.metadata_proxy=None; cfg.proxy=None
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
