#!/usr/bin/env python3
"""Run the RC2 T11/T12 real-network acceptance in a disposable sandbox.

This script never reads application config/history/queue files.  It prepares
one real work through ``Orchestrator``, selects a bounded subset of tracks,
pauses after a non-empty .part exists, recreates the service, resumes via
Range, and writes an evidence JSON report.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import sys
import time
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import ConfigManager
from core.database import LibraryVault
from core.models import TrackItem, WorkMetadata
from core.network import NetworkKernel
from core.orchestrator import Orchestrator

MARKERS = ("config.json", "history.db", "queue.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sandbox", type=Path, required=True)
    parser.add_argument("--rj", default="RJ01276295")
    parser.add_argument("--metadata-proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--max-files", type=int, default=4)
    parser.add_argument("--max-total-bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--duration-minutes", type=int, default=45)
    parser.add_argument("--pause-timeout-seconds", type=int, default=120)
    parser.add_argument("--resume-timeout-seconds", type=int, default=35 * 60)
    return parser.parse_args()


def validate_sandbox(raw: Path) -> Path:
    sandbox = raw.expanduser().resolve(strict=False)
    if sandbox == REPO_ROOT.resolve():
        raise ValueError("sandbox cannot be the repository")
    if sandbox.exists() and any((sandbox / marker).exists() for marker in MARKERS):
        raise ValueError("sandbox contains application runtime markers")
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def select_tracks(tracks: Iterable[TrackItem], max_files: int, max_total: int) -> list[TrackItem]:
    chosen: list[TrackItem] = []
    total = 0
    for track in sorted((item for item in tracks if item.type == "audio" and item.size > 0), key=lambda item: (item.size, item.title)):
        if len(chosen) >= max_files or total + track.size > max_total:
            continue
        chosen.append(track)
        total += track.size
    if len(chosen) < 2:
        raise RuntimeError("bounded selection produced fewer than two files")
    return chosen


def make_config(sandbox: Path, metadata_proxy: str) -> ConfigManager:
    config = ConfigManager()
    config.output_dir = sandbox / "Downloads"
    config.metadata_proxy = metadata_proxy or None
    config.cover_proxy = metadata_proxy or None
    config.download_proxy = None
    config.proxy = None
    config.proxy_download = False
    config.download_fallback_to_proxy = False
    config.file_concurrency = 2
    config.work_concurrency = 1
    config.retry_count = 2
    config.tag_audio = False
    config.sort_files = False
    config.timeout = 30
    return config


async def wait_for_partial(paths: list[Path], timeout: int) -> Path:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for path in paths:
            if path.exists() and path.stat().st_size > 0:
                return path
        await asyncio.sleep(0.25)
    raise TimeoutError("no non-empty .part appeared before pause timeout")


def snapshot(db: LibraryVault, rj_id: str, started: float) -> dict:
    rows = db.get_downloads_by_rj(rj_id)
    return {
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "statuses": {status: sum(row["status"] == status for row in rows) for status in sorted({row["status"] for row in rows})},
        "downloaded_bytes": sum(int(row["downloaded_bytes"] or 0) for row in rows),
        "active_rows": sum(row["status"] in {"queued", "downloading", "paused"} for row in rows),
    }


async def download_selected(orchestrator: Orchestrator, selected: list[TrackItem], meta: WorkMetadata) -> list[asyncio.Task]:
    semaphore = asyncio.Semaphore(orchestrator.config.file_concurrency)
    return [asyncio.create_task(orchestrator.download_file(track, meta, None, semaphore)) for track in selected]


async def run(args: argparse.Namespace) -> dict:
    sandbox = validate_sandbox(args.sandbox)
    logging.basicConfig(
        filename=sandbox / "t11-t12-live-acceptance.log",
        encoding="utf-8",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
    started = time.monotonic()
    report = {"schema": 1, "started_at": datetime.now(timezone.utc).isoformat(), "rj_id": args.rj, "sandbox": str(sandbox), "status": "started", "samples": []}
    config = make_config(sandbox, args.metadata_proxy)
    db = LibraryVault(sandbox / "history.t11-t12.db")
    kernel = NetworkKernel(config)
    orchestrator = Orchestrator(kernel, config, db)
    try:
        meta, targets, _root, _cached = await orchestrator.prepare_work(args.rj, force_refresh=True, allow_duplicate=True)
        if meta is None or not targets:
            raise RuntimeError("metadata preparation failed")
        selected = select_tracks(targets, args.max_files, args.max_total_bytes)
        selected_ids = {item.id or item.title for item in selected}
        for row in db.get_downloads_by_rj(meta.rj_id):
            if row["track_title"] not in {item.title for item in selected}:
                db.upsert_download(row["id"], meta.rj_id, row["track_title"], row["local_path"], "ignored", row["downloaded_bytes"], row["total_bytes"])
        report["selected"] = [{"title": item.title, "size": item.size, "path": str(item.save_path)} for item in selected]
        tasks = await download_selected(orchestrator, selected, meta)
        part = await wait_for_partial([item.save_path.with_suffix(item.save_path.suffix + ".part") for item in selected], args.pause_timeout_seconds)
        before_pause = part.stat().st_size
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.sleep(2)
        paused_size = part.stat().st_size if part.exists() else 0
        report["pause"] = {"part_path": str(part), "before_bytes": before_pause, "after_bytes": paused_size, "stable": before_pause == paused_size, "db": snapshot(db, meta.rj_id, started)}
        await orchestrator.shutdown()
        db.close()

        db = LibraryVault(sandbox / "history.t11-t12.db")
        kernel = NetworkKernel(config)
        resumed = Orchestrator(kernel, config, db)
        resume_tasks = await download_selected(resumed, selected, meta)
        done = await asyncio.wait_for(asyncio.gather(*resume_tasks), timeout=args.resume_timeout_seconds)
        report["resume_results"] = done
        samples_deadline = started + args.duration_minutes * 60
        while time.monotonic() < samples_deadline:
            report["samples"].append(snapshot(db, meta.rj_id, started))
            await asyncio.sleep(60)
        completed = []
        for item in selected:
            if not item.save_path.exists() or item.save_path.stat().st_size != item.size:
                raise RuntimeError(f"missing or invalid final file: {item.save_path}")
            completed.append({"path": str(item.save_path), "size": item.size, "sha256": sha256(item.save_path)})
        report["completed"] = completed
        report["final_db"] = snapshot(db, meta.rj_id, started)
        report["status"] = "pass"
        await resumed.shutdown()
    except Exception as exc:
        report["status"] = "blocked_by_network_or_failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        try:
            await orchestrator.shutdown()
        except Exception:
            pass
    finally:
        try:
            db.close()
        except Exception:
            pass
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        (sandbox / "t11-t12-live-acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    result = asyncio.run(run(parse_args()))
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
