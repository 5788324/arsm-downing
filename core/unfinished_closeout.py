from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

FOCUS_RJ_IDS = (
    "RJ01588893",
    "RJ01534605",
    "RJ00323125",
    "RJ323125",
    "RJ01571951",
    "RJ01572913",
)

ACTIVE_OR_QUEUED_STATUSES = {"queued", "downloading", "resuming"}
FAILED_TO_STALE = "failed_to_stale"
PAUSED_MISSING_TO_STALE = "paused_missing_file_to_stale"
PAUSED_RESUMABLE_DECISION = "paused_resumable_needs_user_decision"
REGISTERED_TO_IGNORED = "registered_to_ignored"
BLOCKED = "blocked"
PLAN_BUCKETS = (
    FAILED_TO_STALE,
    PAUSED_MISSING_TO_STALE,
    PAUSED_RESUMABLE_DECISION,
    REGISTERED_TO_IGNORED,
    BLOCKED,
)


@dataclass
class DownloadPathState:
    local_path: str
    has_target_file: bool
    target_size: int
    part_path: str
    has_part_file: bool
    part_size: int


def inspect_download_path(local_path: str) -> DownloadPathState:
    target = Path(local_path) if local_path else None
    part = Path(f"{local_path}.part") if local_path else None
    has_target = bool(target and target.exists())
    has_part = bool(part and part.exists())
    return DownloadPathState(
        local_path=local_path or "",
        has_target_file=has_target,
        target_size=target.stat().st_size if has_target else 0,
        part_path=str(part) if part else "",
        has_part_file=has_part,
        part_size=part.stat().st_size if has_part else 0,
    )


def classify_download_row(row: sqlite3.Row, active_rj_ids: set[str]) -> Tuple[str | None, Dict]:
    status = row["status"]
    path_state = inspect_download_path(row["local_path"] or "")
    entry = {
        "id": row["id"],
        "rj_id": row["rj_id"],
        "track_title": row["track_title"],
        "status": status,
        "local_path": row["local_path"],
        "downloaded_bytes": row["downloaded_bytes"],
        "total_bytes": row["total_bytes"],
        "error": row["error"],
        "work_status": row["work_status"],
        "work_local_path": row["work_local_path"],
        "has_target_file": path_state.has_target_file,
        "target_size": path_state.target_size,
        "part_path": path_state.part_path,
        "has_part_file": path_state.has_part_file,
        "part_size": path_state.part_size,
        "suggested_status": None,
        "reason": "",
    }

    if status == "completed":
        return None, entry

    if status == "failed":
        if path_state.has_target_file or path_state.has_part_file:
            entry["reason"] = "failed_has_recoverable_file"
            return BLOCKED, entry
        entry["reason"] = "failed_missing_file"
        entry["suggested_status"] = "stale"
        return FAILED_TO_STALE, entry

    if status == "paused":
        if path_state.has_target_file or path_state.has_part_file:
            entry["reason"] = "paused_has_resumable_file"
            return PAUSED_RESUMABLE_DECISION, entry
        entry["reason"] = "paused_missing_file"
        entry["suggested_status"] = "stale"
        return PAUSED_MISSING_TO_STALE, entry

    if status == "registered":
        if row["rj_id"] in active_rj_ids:
            entry["reason"] = "registered_active_or_queued"
            return BLOCKED, entry
        entry["reason"] = "registered_without_active_queue"
        entry["suggested_status"] = "ignored"
        return REGISTERED_TO_IGNORED, entry

    entry["reason"] = f"unsupported_status:{status}"
    return BLOCKED, entry


def build_unfinished_closeout_plan(db_path: Path | str) -> Dict:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """
        SELECT d.*, w.status AS work_status, w.local_path AS work_local_path
        FROM downloads d
        LEFT JOIN works w ON w.rj_id = d.rj_id
        WHERE d.status IN ('failed', 'paused', 'registered', 'completed')
        ORDER BY d.rj_id, d.id
        """
    ).fetchall()
    active_rj_ids = {
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT rj_id FROM downloads WHERE status IN ('queued', 'downloading', 'resuming')"
        ).fetchall()
    }
    conn.close()

    categories: Dict[str, List[Dict]] = {bucket: [] for bucket in PLAN_BUCKETS}
    completed_skipped = 0
    per_rj_status_counts: Dict[str, Counter] = defaultdict(Counter)

    for row in rows:
        per_rj_status_counts[row["rj_id"]][row["status"]] += 1
        bucket, entry = classify_download_row(row, active_rj_ids)
        if bucket is None:
            completed_skipped += 1
            continue
        categories[bucket].append(entry)

    focus = {}
    for rj_id in FOCUS_RJ_IDS:
        grouped = []
        category_counts = Counter()
        for bucket, entries in categories.items():
            for entry in entries:
                if entry["rj_id"] == rj_id:
                    grouped.append({"bucket": bucket, **entry})
                    category_counts[bucket] += 1
        focus[rj_id] = {
            "download_status_counts": dict(per_rj_status_counts.get(rj_id, Counter())),
            "active_or_queued": rj_id in active_rj_ids,
            "plan_entries": grouped,
            "category_counts": dict(category_counts),
        }

    counts = {
        bucket: len(categories[bucket])
        for bucket in PLAN_BUCKETS
    }
    counts["completed_skipped"] = completed_skipped
    counts["completed_included"] = False

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "db_path": str(Path(db_path).resolve()),
        "active_or_queued_rj_ids": sorted(active_rj_ids),
        "counts": counts,
        "categories": categories,
        "focus_rj": focus,
    }


def render_sql_preview(plan: Dict) -> str:
    lines = [
        "-- PREVIEW ONLY -- NO DB WRITES AUTHORIZED",
        "-- RC9.1 unfinished download soft closeout SQL preview",
        f"-- generated_at: {plan['generated_at']}",
        "",
    ]

    def _render_update(bucket: str, target_status: str) -> None:
        entries = plan["categories"][bucket]
        if not entries:
            lines.append(f"-- {bucket}: 0 rows")
            lines.append("")
            return
        ids = ", ".join(f"'{entry['id']}'" for entry in entries)
        lines.append(f"-- {bucket}: {len(entries)} rows")
        lines.append(
            f"-- UPDATE downloads SET status='{target_status}', updated_at=CURRENT_TIMESTAMP WHERE id IN ({ids});"
        )
        lines.append("")

    _render_update(FAILED_TO_STALE, "stale")
    _render_update(PAUSED_MISSING_TO_STALE, "stale")
    _render_update(REGISTERED_TO_IGNORED, "ignored")

    lines.append(f"-- {PAUSED_RESUMABLE_DECISION}: manual confirmation required")
    for entry in plan["categories"][PAUSED_RESUMABLE_DECISION][:20]:
        lines.append(
            f"--   {entry['id']} {entry['rj_id']} reason={entry['reason']} local_path={entry['local_path']} part_path={entry['part_path']}"
        )
    lines.append("")

    lines.append(f"-- {BLOCKED}: blocked from preview execution")
    for entry in plan["categories"][BLOCKED][:40]:
        lines.append(
            f"--   {entry['id']} {entry['rj_id']} status={entry['status']} reason={entry['reason']}"
        )
    lines.append("")
    return "\n".join(lines)


def render_summary_text(plan: Dict) -> str:
    counts = plan["counts"]
    lines = [
        "RC9.1 unfinished download soft closeout summary",
        "",
        f"generated_at: {plan['generated_at']}",
        f"failed_to_stale: {counts[FAILED_TO_STALE]}",
        f"paused_missing_file_to_stale: {counts[PAUSED_MISSING_TO_STALE]}",
        f"paused_resumable_needs_user_decision: {counts[PAUSED_RESUMABLE_DECISION]}",
        f"registered_to_ignored: {counts[REGISTERED_TO_IGNORED]}",
        f"blocked: {counts[BLOCKED]}",
        f"completed_skipped: {counts['completed_skipped']}",
        f"completed_included: {counts['completed_included']}",
        "",
        "Focus RJ:",
    ]
    for rj_id in FOCUS_RJ_IDS:
        item = plan["focus_rj"][rj_id]
        lines.append(
            f"- {rj_id}: statuses={json.dumps(item['download_status_counts'], ensure_ascii=False)} "
            f"active_or_queued={item['active_or_queued']} category_counts={json.dumps(item['category_counts'], ensure_ascii=False)}"
        )
    return "\n".join(lines)


def write_closeout_artifacts(output_root: Path | str, plan: Dict) -> Dict[str, str]:
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    plan_path = output_root / "rc9_1_unfinished_closeout_plan.json"
    sql_path = output_root / "rc9_1_unfinished_closeout_sql_preview.sql"
    summary_path = output_root / "RC9_1_UNFINISHED_CLOSEOUT_SUMMARY.txt"

    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    sql_path.write_text(render_sql_preview(plan), encoding="utf-8")
    summary_path.write_text(render_summary_text(plan), encoding="utf-8")

    return {
        "plan": str(plan_path),
        "sql_preview": str(sql_path),
        "summary": str(summary_path),
    }
