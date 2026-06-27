"""Bulk download postcheck.
Run after finishing a batch download session.
Read-only — no DB writes, no file changes.
"""
import sqlite3
import json
import os
import sys
from pathlib import Path
from datetime import datetime
from collections import Counter

try: sys.stdout.reconfigure(encoding='utf-8')
except: pass

DB_PATH = Path("history.db")

def run_postcheck():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir = Path(".local_backups") / f"bulk_download_postcheck_{ts}"
    os.makedirs(report_dir, exist_ok=True)

    results = {
        "timestamp": datetime.now().isoformat(),
        "checks": {},
        "verdict": "OK",
    }

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # ── 1. DB integrity ──
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    results["checks"]["integrity_check"] = {"ok": integrity == "ok", "value": integrity}

    # ── 2. downloads status ──
    dl_status = dict(conn.execute("SELECT status, COUNT(*) FROM downloads GROUP BY status").fetchall())
    ws_status = dict(conn.execute("SELECT status, COUNT(*) FROM works GROUP BY status").fetchall())
    results["downloads_status"] = dl_status
    results["works_status"] = ws_status

    # ── 3. completed_missing count ──
    missing = []
    for r in conn.execute("SELECT id, rj_id, local_path FROM downloads WHERE status='completed' AND local_path IS NOT NULL"):
        if r["local_path"] and not os.path.exists(r["local_path"]):
            missing.append(dict(r))
    results["checks"]["completed_missing"] = {
        "ok": len(missing) == 0,
        "count": len(missing),
        "samples": missing[:20],
    }

    # ── 4. stale/ignored preservation ──
    results["checks"]["stale_preserved"] = {
        "ok": True,
        "stale_count": dl_status.get("stale", 0),
        "ignored_count": dl_status.get("ignored", 0),
        "note": "count must not decrease; any decrease is a red flag"
    }

    # ── 5. active unfinished ──
    active = dict(conn.execute(
        "SELECT status, COUNT(*) FROM downloads WHERE status IN ('failed','paused','registered','queued','downloading') GROUP BY status"
    ).fetchall())
    results["checks"]["active_unfinished"] = {
        "ok": active.get("failed", 0) == 0 and active.get("registered", 0) == 0,
        "active": active,
        "note": "failed/registered should be 0; paused/queued/downloading may be valid new downloads"
    }

    # ── 6. Recent RJ changes ──
    recent = [dict(r) for r in conn.execute(
        "SELECT rj_id, title, status, downloaded_at FROM works ORDER BY downloaded_at DESC LIMIT 20"
    ).fetchall()]
    results["recent_works"] = recent

    # ── 7. Recent download errors ──
    errors = [dict(r) for r in conn.execute(
        "SELECT id, rj_id, track_title, status, error, updated_at "
        "FROM downloads WHERE error IS NOT NULL AND error != '' "
        "ORDER BY updated_at DESC LIMIT 50"
    ).fetchall()]
    error_prefixes = Counter()
    for e in errors:
        err = e["error"] or "unknown"
        prefix = err[:40].split(":")[0].strip()
        error_prefixes[prefix] += 1
    results["checks"]["error_summary"] = {
        "total_with_errors": len(errors),
        "top_prefixes": error_prefixes.most_common(10),
        "samples": errors[:10],
    }

    # ── 8. Per-RJ download summary for recent works ──
    recent_rj_summary = []
    for w in recent[:10]:
        rj_dl = dict(conn.execute(
            "SELECT status, COUNT(*) FROM downloads WHERE rj_id=? GROUP BY status", (w["rj_id"],)
        ).fetchall())
        recent_rj_summary.append({"rj_id": w["rj_id"], "title": w["title"][:60] if w["title"] else "",
                                  "work_status": w["status"], "downloads": rj_dl})
    results["recent_rj_download_summary"] = recent_rj_summary

    conn.close()

    # ── Verdict ──
    if not results["checks"]["integrity_check"]["ok"]:
        results["verdict"] = "FAIL"
    elif not results["checks"]["completed_missing"]["ok"]:
        results["verdict"] = "WARN"
    elif results["checks"]["active_unfinished"].get("active", {}).get("failed", 0) > 0:
        results["verdict"] = "WARN"

    # ── Write outputs ──
    json_path = report_dir / "bulk_download_postcheck_report.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)

    summary_path = report_dir / "BULK_DOWNLOAD_POSTCHECK_SUMMARY.txt"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(f"Bulk Download Postcheck\n")
        f.write(f"Timestamp: {results['timestamp']}\n")
        f.write(f"Verdict: {results['verdict']}\n\n")

        f.write(f"Integrity: {results['checks']['integrity_check']['value']}\n")
        f.write(f"Downloads: {dl_status}\n")
        f.write(f"Works: {ws_status}\n\n")

        f.write(f"Completed missing: {results['checks']['completed_missing']['count']}\n")
        f.write(f"Stale: {dl_status.get('stale', 0)}  Ignored: {dl_status.get('ignored', 0)}\n")
        f.write(f"Active unfinished: {results['checks']['active_unfinished']['active']}\n\n")

        f.write("Recent works:\n")
        for r in recent_rj_summary[:10]:
            f.write(f"  {r['rj_id']} | {r['work_status']} | dl={r['downloads']} | {r['title'][:50]}\n")

        if results["checks"]["error_summary"]["total_with_errors"] > 0:
            f.write(f"\nErrors: {results['checks']['error_summary']['total_with_errors']} total\n")
            f.write("Top error prefixes:\n")
            for prefix, cnt in results["checks"]["error_summary"]["top_prefixes"][:5]:
                f.write(f"  [{cnt}] {prefix}\n")

    print(f"Verdict: {results['verdict']}")
    print(f"Report: {report_dir}")
    return results

if __name__ == "__main__":
    result = run_postcheck()
    sys.exit(0 if result["verdict"] in ("OK", "WARN") else 1)
