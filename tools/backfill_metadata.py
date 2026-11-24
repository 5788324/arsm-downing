#!/usr/bin/env python3
"""Backfill missing ARSM album metadata from the configured asmr.one API.

This tool reads RJ IDs only from the SQLite database. It never scans, moves, or
modifies media files. Existing track cache and all download/library state are
preserved.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import ConfigManager
from core.database import LibraryVault
from core.network import NetworkKernel

CANDIDATE_TABLES = ("works", "downloads", "library_items", "library_index", "cloud_archives")
REQUIRED_METADATA_KEYS = frozenset({"title", "circle", "tags", "vas", "mainCoverUrl"})
RJ_PATTERN = re.compile(r"^RJ(\d+)$", re.IGNORECASE)


def table_names(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def normalize_rj_id(value: object) -> str | None:
    match = RJ_PATTERN.fullmatch(str(value or "").strip())
    if not match:
        return None
    return f"RJ{match.group(1)}"


def collect_candidate_ids(conn: sqlite3.Connection) -> list[str]:
    """Return every valid RJ ID known by downloads, queue, and library tables."""
    existing = table_names(conn)
    result: set[str] = set()
    for table in CANDIDATE_TABLES:
        if table not in existing:
            continue
        for row in conn.execute(f"SELECT DISTINCT rj_id FROM {table} WHERE rj_id IS NOT NULL"):
            normalized = normalize_rj_id(row[0])
            if normalized:
                result.add(normalized)
    return sorted(result)


def metadata_is_complete(raw: object) -> bool:
    try:
        payload = json.loads(raw or "{}") if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return False
    return isinstance(payload, dict) and REQUIRED_METADATA_KEYS.issubset(payload)


def pending_ids(conn: sqlite3.Connection, *, refresh: bool = False) -> tuple[list[str], int]:
    candidates = collect_candidate_ids(conn)
    if refresh or "metadata_cache" not in table_names(conn):
        return candidates, len(candidates)
    cached = {
        normalize_rj_id(row[0]): row[1]
        for row in conn.execute("SELECT rj_id, metadata_json FROM metadata_cache")
    }
    missing = [rj_id for rj_id in candidates if not metadata_is_complete(cached.get(rj_id))]
    return missing, len(candidates)


def backup_database(source: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"metadata-backfill-{stamp}-{source.name}"
    with sqlite3.connect(str(source)) as src, sqlite3.connect(str(target)) as dst:
        src.backup(dst)
    return target


def write_checkpoint(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def metadata_fields(rj_id: str, payload: dict) -> tuple[str, str, str]:
    title = str(payload.get("title") or rj_id)
    circle_value = payload.get("circle")
    if isinstance(circle_value, dict):
        circle = str(circle_value.get("name") or "")
    else:
        circle = str(circle_value or "")
    cover = str(payload.get("mainCoverUrl") or "")
    return title, circle, cover


async def backfill(args: argparse.Namespace, todo: Iterable[str], total_candidates: int) -> dict:
    todo = list(todo)
    config = ConfigManager.load()
    kernel = NetworkKernel(config)
    vault = LibraryVault(args.db)
    semaphore = asyncio.Semaphore(max(1, args.concurrency))
    result = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "database": str(Path(args.db).resolve()),
        "total_candidates": total_candidates,
        "requested": len(todo),
        "completed": 0,
        "failed": [],
    }
    completed_since_checkpoint = 0

    async def fetch_one(rj_id: str) -> None:
        nonlocal completed_since_checkpoint
        numeric = int(rj_id[2:])
        error = "metadata request failed"
        async with semaphore:
            for attempt in range(1, args.retries + 1):
                payload = await kernel.fetch(f"/api/workInfo/{numeric}")
                if isinstance(payload, dict) and metadata_is_complete(payload):
                    title, circle, cover = metadata_fields(rj_id, payload)
                    vault.upsert_work_metadata(rj_id, title, circle, cover, payload)
                    result["completed"] += 1
                    completed_since_checkpoint += 1
                    if result["completed"] % 25 == 0:
                        print(f"progress {result['completed']}/{len(todo)} failed={len(result['failed'])}", flush=True)
                    if completed_since_checkpoint >= 10:
                        result["updated_at"] = datetime.now().isoformat(timespec="seconds")
                        write_checkpoint(args.checkpoint, result)
                        completed_since_checkpoint = 0
                    return
                error = kernel.last_fetch_error or "API returned incomplete metadata"
                if attempt < args.retries:
                    await asyncio.sleep(min(8, 2 ** attempt))
        result["failed"].append({"rj_id": rj_id, "error": str(error)})

    try:
        await asyncio.gather(*(fetch_one(rj_id) for rj_id in todo))
    finally:
        await kernel.shutdown()
        vault.close()
    result["finished_at"] = datetime.now().isoformat(timespec="seconds")
    result["remaining"] = len(todo) - result["completed"]
    write_checkpoint(args.checkpoint, result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "history.db")
    parser.add_argument("--dry-run", action="store_true", help="Only report candidate counts")
    parser.add_argument("--refresh", action="store_true", help="Refresh complete cache rows too")
    parser.add_argument("--limit", type=int, default=0, help="Limit this run for validation")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--backup-dir", type=Path, default=ROOT / ".local_backups")
    parser.add_argument("--checkpoint", type=Path, default=ROOT / ".local_backups" / "metadata-backfill-state.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.db = args.db.resolve()
    if not args.db.is_file():
        print(json.dumps({"error": f"database not found: {args.db}"}, ensure_ascii=False))
        return 2
    with sqlite3.connect(f"file:{args.db.as_posix()}?mode=ro", uri=True) as conn:
        todo, total_candidates = pending_ids(conn, refresh=args.refresh)
    total_pending = len(todo)
    if args.limit > 0:
        todo = todo[:args.limit]
    summary = {
        "database": str(args.db),
        "total_candidates": total_candidates,
        "already_complete": total_candidates - total_pending,
        "total_pending": total_pending,
        "requested_this_run": len(todo),
        "refresh": args.refresh,
    }
    if args.dry_run or not todo:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    backup = backup_database(args.db, args.backup_dir.resolve())
    print(json.dumps({**summary, "backup": str(backup)}, ensure_ascii=False), flush=True)
    result = asyncio.run(backfill(args, todo, total_candidates))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
