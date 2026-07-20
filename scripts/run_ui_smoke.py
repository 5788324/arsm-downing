#!/usr/bin/env python3
"""Launch the real Flet UI against an isolated config/database sandbox."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import flet as ft

from ui.app import AppController, configure_logging

ACTIVE_MARKERS = ("history.db", "config.json", "queue.json")


def validate_sandbox(path: Path) -> Path:
    sandbox = path.expanduser().resolve(strict=False)
    if sandbox == REPO_ROOT.resolve() or sandbox == Path.cwd().resolve():
        raise ValueError("UI smoke sandbox must be outside the repository/current directory")
    if sandbox.exists() and any(sandbox.iterdir()):
        active = [name for name in ACTIVE_MARKERS if (sandbox / name).exists()]
        suffix = f" ({', '.join(active)})" if active else ""
        raise ValueError(f"UI smoke sandbox must be empty{suffix}")
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sandbox", required=True, type=Path)
    parser.add_argument("--rj", default="RJ99999999")
    parser.add_argument("--mirror", default="http://127.0.0.1:8765")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8550)
    parser.add_argument(
        "--view", choices=("desktop", "web", "headless"),
        default="desktop",
    )
    args = parser.parse_args()

    try:
        sandbox = validate_sandbox(args.sandbox)
    except ValueError as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 2

    config = {
        "output_dir": str(sandbox / "Downloads"),
        "library_paths": [str(sandbox / "Downloads")],
        "work_concurrency": 1,
        "file_concurrency": 1,
        "max_concurrent": 1,
        "chunk_size": 65536,
        "retry_count": 2,
        "retry_backoff": 1,
        "metadata_proxy": None,
        "download_proxy": None,
        "cover_proxy": None,
        "download_fallback_to_proxy": False,
        "mirror": args.mirror.rstrip("/"),
        "tag_audio": False,
        "sort_files": False,
        "dir_template": "{rj_id} {title}",
        "auto_resume_on_start": False,
    }
    (sandbox / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chdir(sandbox)
    configure_logging(sandbox / "logs")

    def target(page: ft.Page):
        controller = AppController(page)
        controller.views[0].rj_input.value = args.rj
        controller.views[0].rj_input.update()

    view = {
        "desktop": ft.AppView.FLET_APP,
        "web": ft.AppView.WEB_BROWSER,
        "headless": None,
    }[args.view]
    ft.app(target=target, host=args.host, port=args.port, view=view)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
