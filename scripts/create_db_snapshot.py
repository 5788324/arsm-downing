#!/usr/bin/env python3
"""Create a consistent read-only snapshot of a live history.db."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from core.database_snapshot import DatabaseSnapshotError, create_database_snapshot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create a verified SQLite snapshot without stopping the downloader. "
            "The source is opened read-only and its WAL/SHM files are not copied."
        )
    )
    parser.add_argument("--source", required=True, help="Path to the active history.db")
    parser.add_argument("--output", required=True, help="New snapshot .db path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = create_database_snapshot(args.source, args.output)
    except (DatabaseSnapshotError, FileNotFoundError) as exc:
        print(f"SNAPSHOT FAILED: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
