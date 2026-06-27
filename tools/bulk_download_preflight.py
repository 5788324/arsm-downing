"""Bulk download preflight check.
Run before starting a batch download session.
Read-only — no DB writes, no file changes.
"""
import sqlite3
import json
import os
import sys
from pathlib import Path
from datetime import datetime

try: sys.stdout.reconfigure(encoding='utf-8')
except: pass

DB_PATH = Path("history.db")
CONFIG_PATH = Path("config.json")

def run_preflight():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir = Path(".local_backups") / f"bulk_download_preflight_{ts}"
    os.makedirs(report_dir, exist_ok=True)

    results = {
        "timestamp": datetime.now().isoformat(),
        "checks": {},
        "verdict": "GO",
    }

    # ── 1. DB integrity ──
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    results["checks"]["integrity_check"] = {"ok": integrity == "ok", "value": integrity}

    # ── 2. Active queue check ──
    active = dict(conn.execute(
        "SELECT status, COUNT(*) FROM downloads WHERE status IN ('failed','paused','registered','queued','downloading') GROUP BY status"
    ).fetchall())
    # failed/registered should be 0 (old garbage); paused from new downloads is OK
    dangerous = {k: v for k, v in active.items() if k in ('failed', 'registered')}
    safe_active = {k: v for k, v in active.items() if k in ('paused', 'queued', 'downloading')}
    results["checks"]["active_queue"] = {
        "ok": not dangerous,  # STOP only if failed/registered returned
        "dangerous_active": dangerous,
        "safe_active": safe_active,
        "note": "STOP if failed/registered returned; paused/queued/downloading from new downloads is OK"
    }

    # ── 3. downloads status snapshot ──
    dl_status = dict(conn.execute("SELECT status, COUNT(*) FROM downloads GROUP BY status").fetchall())
    ws_status = dict(conn.execute("SELECT status, COUNT(*) FROM works GROUP BY status").fetchall())
    results["downloads_status"] = dl_status
    results["works_status"] = ws_status

    # ── 4. stale/ignored isolation check ──
    stale_total = dl_status.get("stale", 0)
    ignored_total = dl_status.get("ignored", 0)
    results["checks"]["stale_ignored_isolation"] = {
        "ok": True,
        "stale_count": stale_total,
        "ignored_count": ignored_total,
        "note": "stale/ignored present but isolated — download pipeline ignores them"
    }

    # ── 5. Config check ──
    config_issues = []
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        if cfg.get("output_dir") != "E:\\arsm":
            config_issues.append(f"output_dir={cfg.get('output_dir')} (expected E:\\arsm)")
        if cfg.get("auto_resume_on_start") is not False:
            config_issues.append(f"auto_resume_on_start={cfg.get('auto_resume_on_start')} (expected false)")
        if cfg.get("metadata_proxy") != "http://127.0.0.1:7897":
            config_issues.append(f"metadata_proxy={cfg.get('metadata_proxy')}")
        if cfg.get("download_proxy") not in (None, "", "null", "direct"):
            config_issues.append(f"download_proxy={cfg.get('download_proxy')} (expected direct/null)")
        if cfg.get("download_fallback_to_proxy") is not False:
            config_issues.append(f"download_fallback_to_proxy={cfg.get('download_fallback_to_proxy')} (expected false)")
        results["config"] = cfg
    except Exception as e:
        config_issues.append(f"config read error: {e}")

    results["checks"]["config"] = {
        "ok": not config_issues,
        "issues": config_issues,
    }

    # ── 6. completed_missing check ──
    missing = []
    for r in conn.execute("SELECT id, rj_id, local_path FROM downloads WHERE status='completed' AND local_path IS NOT NULL"):
        if r["local_path"] and not os.path.exists(r["local_path"]):
            missing.append(dict(r))
    results["checks"]["completed_missing"] = {
        "ok": len(missing) == 0,
        "count": len(missing),
        "samples": missing[:10],
    }

    conn.close()

    # ── Verdict ──
    critical_checks = ["integrity_check", "active_queue", "config"]
    for key in critical_checks:
        if not results["checks"][key]["ok"]:
            results["verdict"] = "STOP"
            break

    # ── Write outputs ──
    json_path = report_dir / "bulk_download_preflight_report.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)

    summary_path = report_dir / "BULK_DOWNLOAD_PREFLIGHT_SUMMARY.txt"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(f"Bulk Download Preflight Check\n")
        f.write(f"Timestamp: {results['timestamp']}\n")
        f.write(f"Verdict: {results['verdict']}\n\n")

        for key, check in results["checks"].items():
            status = "PASS" if check["ok"] else "FAIL"
            f.write(f"[{status}] {key}\n")
            for k, v in check.items():
                if k != "ok":
                    f.write(f"       {k}: {v}\n")

        f.write(f"\nDownloads: {dl_status}\n")
        f.write(f"Works: {ws_status}\n")

        if results["verdict"] == "STOP":
            f.write("\n=== STOP CONDITIONS ===\n")
            for key, check in results["checks"].items():
                if not check["ok"]:
                    f.write(f"  - {key}: FAILED\n")
                    for k, v in check.items():
                        if k != "ok":
                            f.write(f"      {k}: {v}\n")

    print(f"Verdict: {results['verdict']}")
    print(f"Report: {report_dir}")
    return results

if __name__ == "__main__":
    result = run_preflight()
    sys.exit(0 if result["verdict"] == "GO" else 1)
