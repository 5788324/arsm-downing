#!/usr/bin/env python3
"""Isolated ASMR.one metadata and smallest-track download smoke test.

This script never loads the application's config.json or history.db.  It is
intended for a disposable Windows/Codex sandbox while the user's real queue is
still active.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import ConfigManager
from core.database import LibraryVault
from core.network import NetworkKernel
from core.orchestrator import Orchestrator

DEFAULT_RJ = "RJ01575399"
ACTIVE_MARKERS = ("config.json", "history.db", "queue.json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an isolated ASMR.one metadata/smallest-track smoke test.")
    parser.add_argument("--sandbox", required=True, type=Path)
    parser.add_argument("--rj", default=DEFAULT_RJ)
    parser.add_argument("--mirror", default="https://api.asmr-200.com")
    parser.add_argument("--proxy", default="")
    parser.add_argument("--max-bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--metadata-only", action="store_true")
    return parser


def normalize_rj(raw: str) -> str:
    value = raw.strip().upper()
    if value.startswith("RJ"):
        value = value[2:]
    if not value.isdigit() or not 6 <= len(value) <= 8:
        raise ValueError(f"Invalid RJ id: {raw}")
    return f"RJ{int(value):08d}"


def validate_sandbox(path: Path) -> Path:
    sandbox = path.expanduser().resolve(strict=False)
    cwd = Path.cwd().resolve()
    repo = REPO_ROOT.resolve()
    if sandbox in (cwd, repo):
        raise ValueError("Sandbox must not be the current repository directory")
    if sandbox.exists():
        active = [name for name in ACTIVE_MARKERS if (sandbox / name).exists()]
        if active:
            raise ValueError(
                "Sandbox contains active application markers: " + ", ".join(active))
        if any(sandbox.iterdir()):
            raise ValueError("Sandbox must be empty")
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def run_smoke(args: argparse.Namespace) -> dict:
    sandbox = validate_sandbox(args.sandbox)
    rj_id = normalize_rj(args.rj)
    db_path = sandbox / "history.smoke.db"
    output_dir = sandbox / "Downloads"

    config = ConfigManager()
    config.output_dir = output_dir
    config.mirror = args.mirror.rstrip("/")
    config.metadata_proxy = args.proxy or None
    config.download_proxy = args.proxy or None
    config.cover_proxy = args.proxy or None
    config.download_fallback_to_proxy = False
    config.work_concurrency = 1
    config.file_concurrency = 1
    config.retry_count = 2
    config.tag_audio = False
    config.sort_files = False

    db = LibraryVault(db_path)
    kernel = NetworkKernel(config)
    orchestrator = Orchestrator(kernel, config, db)
    report = {
        "schema": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "rj_id": rj_id,
        "mirror": config.mirror,
        "sandbox": str(sandbox),
        "metadata_only": bool(args.metadata_only),
        "status": "started",
    }

    try:
        meta, targets, root_path, from_cache = await orchestrator.prepare_work(
            rj_id, force_refresh=True, allow_duplicate=True)
        if meta is None or not targets:
            raise RuntimeError("Metadata or track preparation failed")

        downloadable = sorted(
            (track for track in targets if track.size > 0),
            key=lambda track: (track.size, track.title),
        )
        report.update({
            "title": meta.title,
            "circle": meta.circle,
            "track_count": len(targets),
            "root_path": str(root_path),
            "from_cache": from_cache,
            "smallest_tracks": [
                {"title": t.title, "size": t.size, "type": t.type}
                for t in downloadable[:10]
            ],
        })

        if args.metadata_only:
            report["status"] = "metadata_ok"
            return report
        if not downloadable:
            raise RuntimeError("No downloadable tracks with a known size")

        selected = downloadable[0]
        report["selected_track"] = {
            "title": selected.title,
            "size": selected.size,
            "type": selected.type,
            "path": str(selected.save_path),
        }
        if selected.size > args.max_bytes:
            raise RuntimeError(
                f"Smallest track is {selected.size} bytes, above --max-bytes {args.max_bytes}")

        ok = await orchestrator.download_file(
            selected, meta, None, asyncio.Semaphore(1))
        if not ok:
            raise RuntimeError("Selected track download failed")
        if not selected.save_path.exists():
            raise RuntimeError("Downloader reported success but the final file is missing")
        actual_size = selected.save_path.stat().st_size
        if actual_size != selected.size:
            raise RuntimeError(
                f"Final size mismatch: {actual_size} != {selected.size}")

        report.update({
            "status": "download_ok",
            "downloaded_size": actual_size,
            "downloaded_sha256": sha256_file(selected.save_path),
        })
        return report
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
        return report
    finally:
        await kernel.shutdown()
        db.close()
        report_path = sandbox / "live-smoke-report.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = asyncio.run(run_smoke(args))
    except ValueError as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("status") in {"metadata_ok", "download_ok"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
