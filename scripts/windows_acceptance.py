#!/usr/bin/env python3
"""Evidence-oriented Windows acceptance runner.

The runner operates only in a fresh evidence directory.  It never writes to the
active application directory.  A live ``history.db`` may be supplied solely as
the read-only source for SQLite online backup.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from typing import Sequence
from urllib.request import urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RJ = "RJ01575399"
PROTECTED_NAMES = {"history.db", "config.json", "queue.json"}


@dataclass
class PhaseResult:
    name: str
    status: str
    command: list[str]
    returncode: int | None
    started_at: str
    finished_at: str
    stdout_log: str | None = None
    stderr_log: str | None = None
    details: dict | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_evidence_dir(path: Path) -> Path:
    evidence = path.expanduser().resolve(strict=False)
    repo = REPO_ROOT.resolve()
    cwd = Path.cwd().resolve()
    if evidence in {repo, cwd}:
        raise ValueError("Evidence directory must be outside the repository/current directory")
    try:
        evidence.relative_to(repo)
    except ValueError:
        pass
    else:
        raise ValueError("Evidence directory must not be inside the repository")
    if evidence.exists() and any(evidence.iterdir()):
        names = {child.name for child in evidence.iterdir()}
        protected = sorted(names & PROTECTED_NAMES)
        suffix = f"; protected markers: {', '.join(protected)}" if protected else ""
        raise ValueError(f"Evidence directory must be empty{suffix}")
    evidence.mkdir(parents=True, exist_ok=True)
    return evidence


def validate_active_db(path: Path | None, evidence: Path) -> Path | None:
    if path is None:
        return None
    source = path.expanduser().resolve(strict=True)
    if not source.is_file():
        raise ValueError(f"Active database is not a file: {source}")
    try:
        source.relative_to(evidence)
    except ValueError:
        return source
    raise ValueError("Active database must not be inside the evidence directory")


def run_phase(name: str, command: Sequence[str], *, cwd: Path,
              logs_dir: Path, env: dict[str, str] | None = None) -> PhaseResult:
    logs_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = logs_dir / f"{name}.stdout.log"
    stderr_path = logs_dir / f"{name}.stderr.log"
    started = utc_now()
    with stdout_path.open("w", encoding="utf-8") as stdout, \
            stderr_path.open("w", encoding="utf-8") as stderr:
        completed = subprocess.run(
            list(command), cwd=cwd, env=env, stdout=stdout, stderr=stderr,
            text=True, check=False,
        )
    return PhaseResult(
        name=name,
        status="passed" if completed.returncode == 0 else "failed",
        command=list(command),
        returncode=completed.returncode,
        started_at=started,
        finished_at=utc_now(),
        stdout_log=str(stdout_path),
        stderr_log=str(stderr_path),
    )


def wait_for_http(url: str, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1.0) as response:
                if response.status < 500:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


def inspect_ui_sandbox(sandbox: Path) -> dict:
    result = {
        "sandbox": str(sandbox),
        "history_db_exists": (sandbox / "history.db").is_file(),
        "queue_json_exists": (sandbox / "queue.json").is_file(),
        "files": [],
    }
    downloads = sandbox / "Downloads"
    if downloads.is_dir():
        for path in sorted(downloads.rglob("*")):
            if path.is_file():
                result["files"].append({
                    "relative_path": path.relative_to(downloads).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": sha256_file(path),
                })
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run isolated Windows acceptance phases and collect evidence."
    )
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--active-db", type=Path)
    parser.add_argument("--rj", default=DEFAULT_RJ)
    parser.add_argument("--mirror", default="https://api.asmr-200.com")
    parser.add_argument("--proxy", default="")
    parser.add_argument("--max-bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--skip-portable", action="store_true")
    parser.add_argument("--skip-live", action="store_true")
    parser.add_argument("--launch-ui", action="store_true")
    parser.add_argument("--ui-port", type=int, default=8550)
    parser.add_argument("--fake-port", type=int, default=8765)
    parser.add_argument("--allow-non-windows", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if platform.system() != "Windows" and not args.allow_non_windows:
        print("STOP: this acceptance runner must execute on Windows", file=sys.stderr)
        return 2

    try:
        evidence = validate_evidence_dir(args.evidence_dir)
        active_db = validate_active_db(args.active_db, evidence)
    except (ValueError, FileNotFoundError) as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 2

    logs_dir = evidence / "logs"
    results: list[PhaseResult] = []
    python = Path(sys.executable).resolve()
    environment = dict(os.environ)
    environment["PYTHONUTF8"] = "1"

    if not args.skip_portable:
        results.append(run_phase(
            "portable-tests",
            [str(python), "-m", "pytest"],
            cwd=REPO_ROOT,
            logs_dir=logs_dir,
            env=environment,
        ))

    blocked = any(result.status == "failed" for result in results)

    if active_db is not None and not blocked:
        snapshot_dir = evidence / "snapshot"
        snapshot_dir.mkdir()
        snapshot = snapshot_dir / "history.snapshot.db"
        results.append(run_phase(
            "database-snapshot",
            [
                str(python), str(REPO_ROOT / "scripts" / "create_db_snapshot.py"),
                "--source", str(active_db), "--output", str(snapshot),
            ],
            cwd=REPO_ROOT,
            logs_dir=logs_dir,
            env=environment,
        ))
        if results[-1].status == "passed":
            results.append(run_phase(
                "snapshot-inspection",
                [
                    str(python), str(REPO_ROOT / "scripts" / "inspect_db_snapshot.py"),
                    "--snapshot", str(snapshot),
                ],
                cwd=REPO_ROOT,
                logs_dir=logs_dir,
                env=environment,
            ))
        blocked = any(result.status == "failed" for result in results)

    if not args.skip_live and not blocked:
        live_dir = evidence / "live-download"
        live_result = run_phase(
            "live-download",
            [
                str(python), str(REPO_ROOT / "scripts" / "live_download_smoke.py"),
                "--sandbox", str(live_dir), "--rj", args.rj,
                "--mirror", args.mirror, "--max-bytes", str(args.max_bytes),
                *(["--proxy", args.proxy] if args.proxy else []),
            ],
            cwd=REPO_ROOT,
            logs_dir=logs_dir,
            env=environment,
        )
        live_report = live_dir / "live-smoke-report.json"
        if live_report.is_file():
            try:
                live_result.details = json.loads(
                    live_report.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                pass
        results.append(live_result)
        blocked = any(result.status == "failed" for result in results)

    if args.launch_ui and not blocked:
        fake_log = logs_dir / "fake-server.log"
        fake_error = logs_dir / "fake-server.error.log"
        fake_command = [
            str(python), str(REPO_ROOT / "scripts" / "fake_asmr_server.py"),
            "--host", "127.0.0.1", "--port", str(args.fake_port),
        ]
        ui_sandbox = evidence / "ui-smoke"
        started = utc_now()
        with fake_log.open("w", encoding="utf-8") as stdout, \
                fake_error.open("w", encoding="utf-8") as stderr:
            server = subprocess.Popen(
                fake_command, cwd=REPO_ROOT, env=environment,
                stdout=stdout, stderr=stderr, text=True,
            )
            try:
                health_url = (
                    f"http://127.0.0.1:{args.fake_port}/api/workInfo/99999999"
                )
                if not wait_for_http(health_url):
                    results.append(PhaseResult(
                        name="ui-smoke",
                        status="failed",
                        command=fake_command,
                        returncode=None,
                        started_at=started,
                        finished_at=utc_now(),
                        stdout_log=str(fake_log),
                        stderr_log=str(fake_error),
                        details={"error": "fake server did not become ready"},
                    ))
                else:
                    ui_result = run_phase(
                        "ui-smoke",
                        [
                            str(python), str(REPO_ROOT / "scripts" / "run_ui_smoke.py"),
                            "--sandbox", str(ui_sandbox),
                            "--rj", "RJ99999999",
                            "--mirror", f"http://127.0.0.1:{args.fake_port}",
                            "--host", "127.0.0.1", "--port", str(args.ui_port),
                            "--view", "desktop",
                        ],
                        cwd=REPO_ROOT,
                        logs_dir=logs_dir,
                        env=environment,
                    )
                    ui_result.details = inspect_ui_sandbox(ui_sandbox)
                    results.append(ui_result)
            finally:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)

    report = {
        "schema": 1,
        "created_at": utc_now(),
        "platform": platform.platform(),
        "python": str(python),
        "repo": str(REPO_ROOT),
        "evidence_dir": str(evidence),
        "active_database_was_modified": False,
        "rj_id": args.rj,
        "phases": [asdict(result) for result in results],
        "ui_requested": bool(args.launch_ui),
        "manual_ui_observation_required": any(
            result.name == "ui-smoke" and result.status == "passed"
            for result in results
        ),
        "blocked_before_remaining_phases": blocked,
    }
    report_path = evidence / "windows-acceptance-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    observation_path = evidence / "ui-observation.json"
    if args.launch_ui:
        observation_path.write_text(json.dumps({
            "schema": 1,
            "layout_ok": None,
            "text_truncation": [],
            "button_semantics": {},
            "observed_states": [],
            "freeze_or_lag": [],
            "screenshots": [],
            "notes": "由 Codex 完成桌面观察后填写；不要操作正式下载器。",
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    failed = [result for result in results if result.status == "failed"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
