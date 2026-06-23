#!/usr/bin/env python3
"""metadata_failed 状态测试 — mock fetch 失败后不写 queued downloads."""
import asyncio, sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def test():
    print(f"\n{'='*60}\n  metadata_failed 状态测试\n{'='*60}\n")
    from core.config import ConfigManager; from core.database import LibraryVault
    from core.network import NetworkKernel; from core.orchestrator import Orchestrator
    import aiohttp

    cfg = ConfigManager.load(); db = LibraryVault(); kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)
    emitted = {}; orc.set_callbacks(lambda e:None, lambda r,s: emitted.update({r:s}))

    original = kernel.fetch
    async def fake(*a,**kw): raise aiohttp.ClientConnectionError("refused")
    kernel.fetch = fake

    meta, targets, root, cached = await orc.prepare_work("RJ99999")
    assert meta is None, "fetch 失败应返回 None"
    st = emitted.get("RJ99999","")
    assert "Metadata failed" in st or "metadata_failed" in st.lower(), f"status={st}"
    print(f"  ✓ status: {st}")

    # Verify no queued downloads written
    dls = db.get_downloads_by_rj("RJ99999")
    assert len(dls) == 0, f"不应有 downloads, 实际 {len(dls)}"
    print(f"  ✓ downloads: 0 (未写 queued)")

    # Verify works.status = metadata_failed
    row = db.conn.execute("SELECT status FROM works WHERE rj_id='RJ99999'").fetchone()
    if row:
        assert row["status"] == "metadata_failed", f"works status={row['status']}"
        print(f"  ✓ works.status = metadata_failed")

    kernel.fetch = original
    db.conn.execute("DELETE FROM works WHERE rj_id='RJ99999'"); db.conn.commit()
    await kernel.shutdown()
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n"); return 0

if __name__=="__main__": sys.exit(asyncio.run(test()))
