#!/usr/bin/env python3
"""Inspect a verified history.db snapshot without touching the live database."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from core.database_inspection import inspect_database_snapshot
from core.database_snapshot import DatabaseSnapshotError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report table and status counts from a verified DB snapshot."
    )
    parser.add_argument("--snapshot", required=True, help="Snapshot .db path")
    args = parser.parse_args(argv)

    try:
        report = inspect_database_snapshot(args.snapshot, require_manifest=True)
    except (DatabaseSnapshotError, FileNotFoundError, OSError) as exc:
        print(f"INSPECTION FAILED: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
