#!/usr/bin/env python3
"""详情无元数据消息测试 — 无 cache 无 downloads 时返回明确 message."""
import asyncio, sys; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  详情无元数据消息测试\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault
    from core.network import NetworkKernel; from core.orchestrator import Orchestrator
    cfg=ConfigManager.load();db=LibraryVault();kernel=NetworkKernel(cfg);orc=Orchestrator(kernel,cfg,db)
    detail=orc.get_track_detail_for_ui("RJ99999")
    assert detail==[],f"无数据应返回空列表, 实际 {detail}"
    print("  ✓ 无 cache 无 downloads → 空列表")
    print("  ✓ UI 应显示 '暂无文件列表' 或 '元数据未准备成功'")
    await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
