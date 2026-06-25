#!/usr/bin/env python3
"""部分失败测试 — monkeypatch orc.download_file 后真实调用 _process_download。

验证: failed 不被 registered 覆盖; works.status=partial.
"""

import asyncio
import sys
import os
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}")
    print(f"  部分失败 monkeypatch 测试")
    print(f"{'='*60}\n")

    from core.config import ConfigManager
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator
    from core.models import WorkMetadata, TrackItem

    rj_code = "RJ99998"
    cfg = ConfigManager.load()
    tmpdir = tempfile.mkdtemp()
    cfg.output_dir = Path(tmpdir)

    db = LibraryVault()
    kernel = NetworkKernel(cfg)
    orc = Orchestrator(kernel, cfg, db)

    # ── Setup meta & tracks ──
    meta = WorkMetadata(
        rj_id=rj_code, title="Test Partial", circle="TC",
        cv=[], tags=[], price=0, source_url="", dl_count=0,
        rating=0.0, release_date="", cover_url="")
    root = cfg.output_dir / f"{rj_code} Test Partial"
    root.mkdir(parents=True, exist_ok=True)

    t1_path = root / "ok1.mp3"
    t1_path.write_bytes(b"y" * 100)
    t1 = TrackItem(id="a1", title="ok1", type="audio",
                   url="", size=100, save_path=t1_path)

    t2_path = root / "fail1.wav"
    t2 = TrackItem(id="a2", title="fail1", type="audio",
                   url="", size=200, save_path=t2_path)

    t3_path = root / "ok2.flac"
    t3_path.write_bytes(b"z" * 300)
    t3 = TrackItem(id="a3", title="ok2", type="audio",
                   url="", size=300, save_path=t3_path)

    targets = [t1, t2, t3]

    # Pre-write queued states
    for t in targets:
        dl_id = orc._make_dl_id(rj_code, t.id, t.save_path, t.title)
        db.upsert_download(dl_id, rj_code, t.title, str(t.save_path),
                           'queued', 0, t.size)

    # ── Monkeypatch download_file ──
    call_log = []

    async def fake_download(track, meta, cover_path, file_sem):
        call_log.append(track.id)
        # t1, t3 succeed; t2 fails
        if track.id == "a2":
            # Write failed state to DB (simulating real failure)
            dl_id = orc._make_dl_id(rj_code, track.id, track.save_path, track.title)
            db.upsert_download(dl_id, rj_code, track.title, str(track.save_path),
                               'failed', 0, track.size, error="simulated")
            return False
        # Success: create dummy file if not exists
        if not track.save_path.exists():
            track.save_path.write_bytes(b"x" * track.size)
        dl_id = orc._make_dl_id(rj_code, track.id, track.save_path, track.title)
        db.upsert_download(dl_id, rj_code, track.title, str(track.save_path),
                           'completed', track.size, track.size)
        return True

    orc.download_file = fake_download

    # ── Real call to _process_download ──
    print("── 调用真实的 _process_download (2 成功, 1 失败) ──")
    orc.set_callbacks(
        lambda *a: None,
        lambda rj, st: print(f"  work_status: {rj} → {st}")
    )
    await orc._process_download(rj_code, meta, targets, root)

    # ── Verify DB state ──
    print("\n── 验证 DB 状态 ──")
    rows = db.get_downloads_by_rj(rj_code)
    states = {}
    for row in rows:
        states[row["id"]] = row["status"]
        print(f"  {row['id'][:30]}: {row['status']}")

    dl1_id = orc._make_dl_id(rj_code, "a1", t1_path, "ok1")
    dl2_id = orc._make_dl_id(rj_code, "a2", t2_path, "fail1")
    dl3_id = orc._make_dl_id(rj_code, "a3", t3_path, "ok2")

    assert states.get(dl1_id) == 'registered', \
        f"ok1 应为 registered, 实际: {states.get(dl1_id)}"
    assert states.get(dl2_id) == 'failed', \
        f"fail1 应为 failed(不被覆盖), 实际: {states.get(dl2_id)}"
    assert states.get(dl3_id) == 'registered', \
        f"ok2 应为 registered, 实际: {states.get(dl3_id)}"

    print(f"\n  ✓ failed 未被子序列覆盖")

    # ── Verify works.status is partial ──
    row = db.conn.execute(
        "SELECT status FROM works WHERE rj_id=?", (rj_code,)
    ).fetchone()
    ws = row["status"] if row else "missing"
    print(f"  works.status: {ws}")
    assert ws == 'partial', \
        f"works 应为 partial(部分失败), 实际: {ws}"

    # Cleanup
    db.conn.execute("DELETE FROM downloads WHERE rj_id=?", (rj_code,))
    db.conn.execute("DELETE FROM works WHERE rj_id=?", (rj_code,))
    db.conn.commit()
    await kernel.shutdown()
    import shutil
    shutil.rmtree(tmpdir)

    print(f"\n{'='*60}")
    print(f"  ✓ 部分失败 monkeypatch 测试通过")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
