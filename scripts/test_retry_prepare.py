#!/usr/bin/env python3
"""retry_prepare 测试 — 第一次失败, 第二次成功."""
import asyncio, sys; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  retry_prepare 测试\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault
    from core.network import NetworkKernel; from core.orchestrator import Orchestrator
    import aiohttp
    cfg=ConfigManager.load();db=LibraryVault();kernel=NetworkKernel(cfg);orc=Orchestrator(kernel,cfg,db)
    emitted={};orc.set_callbacks(lambda e:None,lambda r,s:emitted.update({r:s}))
    original=kernel.fetch
    call=0
    async def fake(endpoint,*a,**kw):
        nonlocal call;call+=1
        if call<=1:raise aiohttp.ClientConnectionError("refused")
        if "workInfo" in endpoint:
            return {"title":"OK","circle":{"name":"TC"},"vas":[],"tags":[],"price":0,"source_url":"","dl_count":0,"rate_average_2dp":0,"release_date":"","mainCoverUrl":""}
        return [{"type":"audio","title":"t.mp3","id":"1","mediaDownloadUrl":"http://x/t.mp3","size":100}]
    kernel.fetch=fake
    m1,_,_,_ = await orc.prepare_work("RJ99999",force_refresh=True)
    assert m1 is None;print(f"  ✓ 第一次: metadata_failed")
    m2,_,_,_ = await orc.prepare_work("RJ99999",force_refresh=True)
    assert m2 is not None;print(f"  ✓ 第二次: 成功 ({m2.title})")
    kernel.fetch=original
    db.conn.execute("DELETE FROM works WHERE rj_id='RJ99999'");db.conn.commit()
    db.conn.execute("DELETE FROM downloads WHERE rj_id='RJ99999'");db.conn.commit()
    db.invalidate_cache("RJ99999");await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
