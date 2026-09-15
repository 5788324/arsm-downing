#!/usr/bin/env python3
"""v1.0.1 headless stress acceptance for PR #21 (Issue #20 / #19).

Drives the REAL product code (Orchestrator + DownloadWorkerPool +
SignedUrlRefresher + download_file) against a local aiohttp server and checks
the invariants the GUI acceptance depends on:

  1. 9 works x files-per-work (~2700 files total) via the bounded worker pool;
     every file starts with an EXPIRED signed URL (server 403), the single-
     flight refresher supplies a fresh URL, and each stale URL is hit EXACTLY
     ONCE (no retry storm); one refresh per RJ.
  2. A concentrated 400/401/403 burst work asserts the same single-flight +
     no-retry-storm property with rotating HTTP statuses.
  3. Recovery: a work pre-seeded at 9/10 complete is resumed; emitted progress
     is monotonic (never jumps back to 0%) and the work ratio goes
     0.9 -> 0.95 -> 1.0.
  4. psutil samples RSS + CPU every 10s for the whole duration; asserts the
     process does not grow without bound.

Writes an evidence JSON into the sandbox.  This is a headless run; the visual
GUI checks (DPI / tray / resolution / click-through) still require a human at
the Windows desktop.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys
import time
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import psutil
from aiohttp import web

from core.config import ConfigManager
from core.database import LibraryVault
from core.download_workers import DownloadWorkerPool
from core.models import ProgressEvent, TrackItem, WorkMetadata
from core.network import NetworkKernel
from core.orchestrator import Orchestrator
from core.url_refresh import SignedUrlRefresher

logging.basicConfig(level=logging.WARNING)

MARKERS = ("config.json", "history.db", "queue.json")
FILE_SIZE = 64 * 1024        # 64 KiB per stress file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sandbox", type=Path, required=True)
    parser.add_argument("--rj-count", type=int, default=9)
    parser.add_argument("--files-per-work", type=int, default=300)
    parser.add_argument("--burst-files", type=int, default=300)
    parser.add_argument("--duration-minutes", type=float, default=30.0)
    parser.add_argument("--file-concurrency", type=int, default=6)
    return parser.parse_args()


def validate_sandbox(raw: Path) -> Path:
    sandbox = raw.expanduser().resolve(strict=False)
    if sandbox == REPO_ROOT.resolve():
        raise ValueError("sandbox cannot be the repository")
    if sandbox.exists() and any((sandbox / marker).exists() for marker in MARKERS):
        raise ValueError("sandbox contains application runtime markers")
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


def make_config(sandbox: Path) -> ConfigManager:
    config = ConfigManager()
    config.output_dir = sandbox / "Downloads"
    config.file_concurrency = 6
    config.work_concurrency = 1
    config.metadata_concurrency = 1
    config.retry_count = 2
    config.retry_backoff = 1
    config.chunk_size = 64 * 1024
    config.tag_audio = False
    config.sort_files = False
    config.download_fallback_to_proxy = False
    config.download_proxy = None
    config.proxy = None
    config.proxy_download = False
    config.timeout = 30
    return config


def meta_for(rj_id: str, title: str) -> WorkMetadata:
    return WorkMetadata(
        rj_id=rj_id, title=title, circle="Stress", cv=[], tags=[],
        price=0, dl_count=0, source_url="", rating=0.0,
        release_date="", cover_url="",
    )


def stale_url(base: str, rj_id: str, idx: int) -> str:
    return f"{base}/stale/{rj_id}/{idx}?X-Amz-Signature=EXPIRED123"


def fresh_url(base: str, rj_id: str, idx: int) -> str:
    return f"{base}/fresh/{rj_id}/{idx}?X-Amz-Signature=GOOD456"


class StaleCounter:
    def __init__(self) -> None:
        self.stale_hits: dict[str, int] = {}
        self.burst_status: dict[str, list[int]] = {}
        self.burst_hits: dict[str, int] = {}

    def note(self, url: str) -> None:
        self.stale_hits[url] = self.stale_hits.get(url, 0) + 1


async def make_server(sandbox: Path, counter: StaleCounter) -> tuple[web.AppRunner, str]:
    src = sandbox / "src"
    src.mkdir(parents=True, exist_ok=True)

    def ensure_file(path: Path) -> Path:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x" * FILE_SIZE)
        return path

    async def stale(request: web.Request) -> web.Response:
        counter.note(str(request.url))
        return web.Response(status=403, text="signed url expired")

    async def fresh(request: web.Request) -> web.Response:
        rj = request.match_info["rj"]
        idx = request.match_info["idx"]
        path = ensure_file(src / rj / f"{idx}.bin")
        return web.FileResponse(path)

    async def burst(request: web.Request) -> web.Response:
        key = f"{request.match_info['rj']}/{request.match_info['idx']}"
        counter.note(str(request.url))
        idx = int(request.match_info["idx"])
        status = (400, 401, 403)[idx % 3]   # exercise all three statuses
        counter.burst_hits[key] = counter.burst_hits.get(key, 0) + 1
        return web.Response(status=status, text="expired signed url")

    app = web.Application()
    app.router.add_get("/stale/{rj}/{idx}", stale)
    app.router.add_get("/fresh/{rj}/{idx}", fresh)
    app.router.add_get("/burst/{rj}/{idx}", burst)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}"


class ProgressProbe:
    """Capture emitted progress and assert monotonic per (rj, track)."""

    def __init__(self) -> None:
        self.events: list[ProgressEvent] = []
        self.last_per_track: dict[tuple, int] = {}
        self.regressions: list[dict] = []
        self.work_downloaded: dict[str, int] = {}

    def __call__(self, event: ProgressEvent) -> None:
        self.events.append(event)
        key = (event.rj_id, event.track_id)
        prev = self.last_per_track.get(key, 0)
        if event.downloaded_bytes < prev:
            self.regressions.append({
                "rj": event.rj_id, "track": event.track_title,
                "prev": prev, "now": event.downloaded_bytes,
            })
        self.last_per_track[key] = max(prev, event.downloaded_bytes)
        self.work_downloaded[event.rj_id] = max(
            self.work_downloaded.get(event.rj_id, 0), event.downloaded_bytes)

    def work_ratio(self, rj_id: str, expected: int) -> float:
        total = 0
        for event in self.events:
            if event.rj_id == rj_id:
                total = max(total, event.downloaded_bytes)
        return total / expected if expected else 0.0


def build_targets(base: str, rj_id: str, count: int, size: int,
                  save_root: Path, burst: bool = False) -> list[TrackItem]:
    targets = []
    for idx in range(count):
        url = (f"{base}/burst/{rj_id}/{idx}" if burst
               else stale_url(base, rj_id, idx))
        targets.append(TrackItem(
            id=f"f{idx}", title=f"{rj_id}-{idx}.bin", type="file",
            url=url, size=size,
            save_path=save_root / rj_id / f"{idx}.bin",
        ))
    return targets


async def run_work(orchestrator: Orchestrator, meta: WorkMetadata,
                   targets: list[TrackItem], refresher: SignedUrlRefresher,
                   concurrency: int) -> dict:
    sem = asyncio.Semaphore(concurrency)
    pool = DownloadWorkerPool(
        worker_count=concurrency,
        process=lambda t: orchestrator.download_file(
            t, meta, None, sem, refresher),
        key_of=lambda t: id(t),
    )
    results = await pool.run(targets)
    ok = sum(1 for r in results.values() if r is True)
    return {"total": len(targets), "ok": ok,
            "failed": len(targets) - ok}


async def sampler_task(runtime: float, samples: list[dict],
                       snapshot_fn: Callable[[], dict]) -> None:
    proc = psutil.Process()
    started = time.monotonic()
    while time.monotonic() - started < runtime:
        try:
            mem = proc.memory_info().rss
            cpu = proc.cpu_percent(interval=None)
        except Exception:
            mem = cpu = -1
        samples.append({
            "t": round(time.monotonic() - started, 1),
            "rss_mb": round(mem / 1024 / 1024, 1),
            "cpu_pct": round(cpu, 1),
            "db": snapshot_fn(),
        })
        await asyncio.sleep(10)


async def run(args: argparse.Namespace, sandbox: Path,
              counter: StaleCounter, base: str, runner: web.AppRunner,
              db: LibraryVault, kernel: NetworkKernel) -> dict:
    config = make_config(sandbox)
    config.file_concurrency = args.file_concurrency
    orchestrator = Orchestrator(kernel, config, db)
    probe = ProgressProbe()
    orchestrator.set_callbacks(probe, lambda rj, st: None)

    started = time.monotonic()
    results: dict[str, Any] = {}
    refresher_map: dict[str, SignedUrlRefresher] = {}
    save_root = sandbox / "Downloads"

    def make_refresher(rj_id: str, count: int):
        async def _fetch(_rj, rj=rj_id, n=count):
            await asyncio.sleep(0)
            return [
                TrackItem(id=f"f{i}", title=f"{rj}-{i}.bin", type="file",
                          url=f"{base}/fresh/{rj}/{i}", size=FILE_SIZE,
                          save_path=save_root / rj / f"{i}.bin")
                for i in range(n)
            ]
        ref = SignedUrlRefresher(_fetch)
        refresher_map[rj_id] = ref
        return ref

    # Phase 1: 9 works x files-per-work, all via expired signed URLs.
    for w in range(args.rj_count):
        rj_id = f"RJ{100000 + w:06d}"
        meta = meta_for(rj_id, f"Stress Work {w}")
        targets = build_targets(base, rj_id, args.files_per_work, FILE_SIZE, save_root)
        ref = make_refresher(rj_id, args.files_per_work)
        res = await run_work(orchestrator, meta, targets, ref, args.file_concurrency)
        results[f"work_{w}"] = res

    # Phase 2: concentrated 400/401/403 burst work (single-flight refresh).
    burst_rj = "RJ200000"
    meta_b = meta_for(burst_rj, "Burst")
    burst_targets = build_targets(base, burst_rj, args.burst_files, FILE_SIZE,
                                  save_root, burst=True)
    ref_b = make_refresher(burst_rj, args.burst_files)
    results["burst"] = await run_work(
        orchestrator, meta_b, burst_targets, ref_b, args.file_concurrency)

    # Phase 3: recovery — 9/10 complete work resumed; DB ratio 0.9 -> 1.0 and
    # per-track emitted progress is strictly monotonic (never back to 0%).
    rec_rj = "RJ300000"
    rec_meta = meta_for(rec_rj, "Recovery")
    rec_root = save_root / rec_rj
    rec_root.mkdir(parents=True, exist_ok=True)
    rec_targets: list[TrackItem] = []
    for i in range(10):
        path = rec_root / f"{i}.bin"
        if i < 9:
            path.write_bytes(b"y" * FILE_SIZE)
            db.upsert_download(f"{rec_rj}:{i}", rec_rj, f"{rec_rj}-{i}.bin",
                               str(path), "completed", FILE_SIZE,
                               FILE_SIZE)
        rec_targets.append(TrackItem(
            id=f"f{i}", title=f"{rec_rj}-{i}.bin", type="file",
            url=f"{base}/fresh/{rec_rj}/{i}", size=FILE_SIZE,
            save_path=path,
        ))
    # 10th file is the resume target: a queued row with the SAME download id
    # download_file will compute, plus a non-empty .part so the download must
    # resume via HTTP 206 Range to completion.
    rec_dl_id = Orchestrator._make_dl_id(
        rec_rj, "f9", rec_root / "9.bin", f"{rec_rj}-9.bin")
    rec_part = rec_root / "9.bin.part"
    rec_part.write_bytes(b"z" * (FILE_SIZE // 2))
    db.upsert_download(rec_dl_id, rec_rj, f"{rec_rj}-9.bin",
                       str(rec_root / "9.bin"), "downloading", 0, FILE_SIZE)
    db.conn.commit()

    def db_ratio(rj_id: str) -> float:
        row = db.conn.execute(
            "SELECT SUM(downloaded_bytes), SUM(total_bytes) "
            "FROM downloads WHERE rj_id = ?", (rj_id,)).fetchone()
        dl, total = int(row[0] or 0), int(row[1] or 0)
        return (dl / total) if total else 0.0

    before = db_ratio(rec_rj)          # 0.9
    ref_rec = SignedUrlRefresher(
        lambda r: [TrackItem(id=f"f{i}", title=f"{rec_rj}-{i}.bin",
                             type="file", url=f"{base}/fresh/{rec_rj}/{i}",
                             size=FILE_SIZE,
                             save_path=rec_root / f"{i}.bin")
                   for i in range(10)])
    rec_sem = asyncio.Semaphore(1)
    pool = DownloadWorkerPool(
        worker_count=1,
        process=lambda t: orchestrator.download_file(
            t, rec_meta, None, rec_sem, ref_rec),
        key_of=lambda t: id(t),
    )
    rec_result = await pool.run([rec_targets[9]])
    after = db_ratio(rec_rj)           # 1.0
    rec_row = db.conn.execute(
        "SELECT status, downloaded_bytes FROM downloads "
        "WHERE rj_id = ? AND track_title = ?",
        (rec_rj, f"{rec_rj}-9.bin")).fetchone()

    results["recovery"] = {
        "ratio_before_resume": round(before, 3),
        "ratio_after_resume": round(after, 3),
        "pool_result": rec_result,
        "final_file_bytes": (rec_root / "9.bin").stat().st_size,
        "final_row": {"status": rec_row[0],
                      "downloaded": int(rec_row[1])} if rec_row else None,
    }

    elapsed = time.monotonic() - started
    refresh_counts = {rj: ref.refresh_count_for(rj)
                      for rj, ref in refresher_map.items()}
    results["elapsed_seconds"] = round(elapsed, 2)
    results["refresh_counts"] = refresh_counts
    results["refresh_single_flight_ok"] = all(
        c == 1 for c in refresh_counts.values())
    results["stale_hits"] = counter.stale_hits
    results["progress_regressions"] = probe.regressions[:20]
    results["total_files"] = (args.rj_count * args.files_per_work
                              + args.burst_files)
    return results


async def main() -> int:
    args = parse_args()
    sandbox = validate_sandbox(args.sandbox)
    counter = StaleCounter()
    db = LibraryVault(sandbox / "history.db")
    config = make_config(sandbox)
    kernel = NetworkKernel(config)
    runner, base = await make_server(sandbox, counter)

    samples: list[dict] = []
    probe_progress: dict = {}

    def snapshot_fn() -> dict:
        rows = db.conn.execute(
            "SELECT status, COUNT(*) FROM downloads GROUP BY status").fetchall()
        return {str(r[0]): r[1] for r in rows}

    sampler = asyncio.create_task(
        sampler_task(args.duration_minutes * 60, samples, snapshot_fn))

    try:
        results = await run(args, sandbox, counter, base, runner, db, kernel)
        # Downloads are done; keep the DB open for the sampler's snapshots.
        await kernel.shutdown()
        await runner.cleanup()
    except Exception:
        await kernel.shutdown()
        await runner.cleanup()
        raise

    # Observation phase: the sampler keeps sampling RSS/CPU + DB snapshots for
    # the remaining duration; the DB must stay open until it finishes.
    await sampler
    db.close()

    rss = [s["rss_mb"] for s in samples if s["rss_mb"] >= 0]
    cpus = [s["cpu_pct"] for s in samples if s["cpu_pct"] >= 0]
    evidence = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "args": {k: (str(v) if isinstance(v, Path) else v)
                 for k, v in vars(args).items()},
        "duration_minutes": args.duration_minutes,
        "results": results,
        "samples_count": len(samples),
        "rss_min_mb": round(min(rss), 1) if rss else None,
        "rss_max_mb": round(max(rss), 1) if rss else None,
        "rss_last_mb": round(rss[-1], 1) if rss else None,
        "cpu_max_pct": round(max(cpus), 1) if cpus else None,
        "cpu_avg_pct": round(sum(cpus) / len(cpus), 1) if cpus else None,
        "samples": samples[-50:],
    }
    report = sandbox / "evidence.json"
    report.write_text(json.dumps(evidence, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))

    # ── assertions ──
    problems: list[str] = []
    ok = results.get("recovery", {})
    if not results.get("refresh_single_flight_ok"):
        problems.append("single-flight violated (a refresh ran more than once)")
    for name, res in results.items():
        if isinstance(res, dict) and "ok" in res and res.get("failed"):
            problems.append(f"{name}: {res['failed']} files failed")
    stale = results.get("stale_hits", {})
    multi_hit = [url for url, n in stale.items() if n > 1]
    if multi_hit:
        problems.append(f"retry storm: {len(multi_hit)} URLs hit more than once")
    if results.get("progress_regressions"):
        problems.append("progress regressed (downloaded went backwards)")
    if ok.get("ratio_before_resume") != 0.9:
        problems.append(f"recovery baseline != 0.9: {ok.get('ratio_before_resume')}")
    if not ok.get("ratio_after_resume", 0) >= 0.99:
        problems.append(f"recovery not ~100%: {ok.get('ratio_after_resume')}")
    if rss and len(rss) >= 3:
        # Steady-state plateau: allow a bounded rise during the download phase,
        # but a 30-minute run must not grow without bound.
        if rss[-1] > max(rss[0], 200) * 2 + 500:
            problems.append("RSS grew without bound")
    if cpus and len(cpus) >= 3:
        # Sustained abnormal CPU (a 30-min run is mostly idle after download).
        if sum(cpus) / len(cpus) > 200:
            problems.append(f"sustained high CPU: avg {sum(cpus)/len(cpus):.0f}%")

    if problems:
        print("FAILURES:")
        for p in problems:
            print(" -", p)
        return 2
    print("ACCEPTANCE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

