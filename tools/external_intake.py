"""External intake — complete metadata refresh + filelist verify + tree normalize + quarantine.
Usage:
  python tools/external_intake.py --dry-run [--refresh-metadata] [--verify-filelist]
  python tools/external_intake.py --execute --confirm-bulk
"""
import sqlite3, json, os, sys, re, shutil, asyncio, hashlib, argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict

try: sys.stdout.reconfigure(encoding='utf-8')
except: pass

E_ROOT = Path(r"E:\arsm")
QUARANTINE_BASE = Path(r"E:\arsm_quarantine_external")
RJ_RE = re.compile(r'(?:RJ)?(\d{6,8})', re.IGNORECASE)

def norm_rj(name: str) -> str:
    m = RJ_RE.search(name)
    return f"RJ{int(m.group(1)):08d}" if m else ""

def safe_name(s: str, maxlen=80) -> str:
    return re.sub(r'[<>:"/\\|?*]', '', (s or ""))[:maxlen]


# ══════════════════════════════════════════════
# SCAN
# ══════════════════════════════════════════════
def scan_top_dirs():
    """Scan E:\\arsm top-level. Returns per-dir info + plan."""
    dirs_info = []
    rj_seen = {}
    plan = defaultdict(int)
    plan["blockers"] = []

    if not E_ROOT.exists():
        return dirs_info, dict(plan)

    for d in sorted(E_ROOT.iterdir()):
        if not d.is_dir(): continue
        rj_id = norm_rj(d.name)
        if not rj_id:
            plan["no_rj_match"] += 1
            plan["quarantine_required"] += 1
            dirs_info.append({"dir": str(d), "rj_id": "", "action": "quarantine", "reason": "no_rj_match"})
            continue

        if rj_id in rj_seen:
            plan["duplicate_rj"] += 1
            plan["quarantine_required"] += 1
            dirs_info.append({"dir": str(d), "rj_id": rj_id, "action": "quarantine",
                              "reason": f"duplicate of {rj_seen[rj_id]}"})
            continue
        rj_seen[rj_id] = d

        info = _classify_dir(d, rj_id)
        dirs_info.append(info)
        plan[info["action"]] = plan.get(info["action"], 0) + 1

    plan["scanned_top_dirs"] = len(dirs_info)
    plan["unique_rj"] = len(rj_seen)
    blockers = compute_blockers(dirs_info)
    plan["blockers"] = len(blockers)
    plan["blocker_list"] = blockers[:20]
    plan["can_execute"] = len(blockers) == 0
    return dirs_info, dict(plan)


def compute_blockers(dirs_info: list) -> list:
    """Return hard blockers that must be resolved before bulk execution."""
    blockers = []
    for info in dirs_info:
        action = info.get("action")
        reason = info.get("reason", "")
        rj_id = info.get("rj_id") or info.get("name") or info.get("dir") or "UNKNOWN"
        if action == "quarantine":
            blockers.append(f"{rj_id}: {reason or 'quarantine'}")
        if info.get("has_part"):
            msg = f"{rj_id}: has_part"
            if msg not in blockers:
                blockers.append(msg)
        if info.get("is_empty"):
            msg = f"{rj_id}: empty"
            if msg not in blockers:
                blockers.append(msg)
    return blockers


def scan_structure():
    """UI-compatible read-only scan result."""
    dirs_info, plan = scan_top_dirs()
    plan["actions"] = dirs_info
    return plan


def _classify_dir(d: Path, rj_id: str) -> dict:
    name = d.name
    is_pure = name == rj_id
    files_at_root = [f for f in d.iterdir() if f.is_file()] if d.is_dir() else []
    subdirs = [f for f in d.iterdir() if f.is_dir()] if d.is_dir() else []
    has_part = any(f.suffix == ".part" for f in d.rglob("*"))
    is_empty = not files_at_root and not subdirs

    info = {"dir": str(d), "rj_id": rj_id, "name": name, "is_pure_rj": is_pure,
            "files_at_root": len(files_at_root), "subdirs": len(subdirs),
            "has_part": has_part, "is_empty": is_empty}

    if has_part:
        info["action"] = "quarantine"; info["reason"] = "has_part_files"
    elif is_empty:
        info["action"] = "quarantine"; info["reason"] = "empty_directory"
    elif is_pure and subdirs:
        info["action"] = "already_normalized"
    elif is_pure and not subdirs and files_at_root:
        info["action"] = "needs_title_layer"
    elif not is_pure:
        info["action"] = "needs_rename_top_level"
    else:
        info["action"] = "already_normalized"
    return info


# ══════════════════════════════════════════════
# METADATA REFRESH
# ══════════════════════════════════════════════
async def refresh_metadata(rj_ids: list, config) -> dict:
    """Refresh metadata_cache for given RJs. Returns report."""
    report = {"refreshed": 0, "failed": 0, "failed_rjs": [], "total": len(rj_ids)}
    from core.database import LibraryVault
    from core.network import NetworkKernel
    from core.orchestrator import Orchestrator
    db = LibraryVault()
    kernel = NetworkKernel(config)
    orc = Orchestrator(kernel, config, db)
    await orc.boot_workers()

    for rj_id in rj_ids:
        try:
            meta, targets, _, _ = await orc.prepare_work(rj_id, force_refresh=True)
            if meta:
                report["refreshed"] += 1
            else:
                report["failed"] += 1
                report["failed_rjs"].append(rj_id)
        except Exception:
            report["failed"] += 1
            report["failed_rjs"].append(rj_id)

    await orc.shutdown()
    return report


# ══════════════════════════════════════════════
# FILELIST VERIFY
# ══════════════════════════════════════════════
def verify_filelist(rj_id: str, disk_dir: Path, db_conn) -> dict:
    """Compare metadata tracks vs disk files."""
    result = {"rj_id": rj_id, "total_tracks": 0, "matched": 0, "missing_audio": [],
              "missing_other": 0, "has_part": False, "empty_dir": False, "verdict": "ok"}

    cached = db_conn.execute("SELECT tracks_json FROM metadata_cache WHERE rj_id=?", (rj_id,)).fetchone()
    if not cached or not cached[0]:
        result["verdict"] = "no_metadata"
        return result

    try: tracks = json.loads(cached[0])
    except: result["verdict"] = "bad_metadata"; return result

    # Collect actual disk files
    disk_files = {}
    for f in disk_dir.rglob("*") if disk_dir.exists() else []:
        if f.is_file():
            disk_files[f.name.lower()] = f

    # Check .part
    if any(k.endswith(".part") for k in disk_files):
        result["has_part"] = True
        result["verdict"] = "has_part"
        return result

    if not disk_files:
        result["empty_dir"] = True
        result["verdict"] = "empty"
        return result

    # Extract leaf files from tracks
    track_names = _extract_track_names(tracks)
    result["total_tracks"] = len(track_names)

    for tname in track_names:
        tl = tname.lower()
        # Loose match: stem match or contains match
        found = False
        for dname, dpath in disk_files.items():
            dstem = Path(dname).stem.lower()
            tstem = Path(tl).stem.lower()
            if dstem == tstem or tstem in dstem or dstem in tstem:
                found = True
                break
        if found:
            result["matched"] += 1
        else:
            # Classify: audio or other
            ext = Path(tl).suffix.lower()
            if ext in (".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".opus"):
                result["missing_audio"].append(tname)
            else:
                result["missing_other"] += 1

    if result["missing_audio"]:
        result["verdict"] = "missing_audio_files"
    elif result["missing_other"] > result["total_tracks"] * 0.5:
        result["verdict"] = "severely_mismatched"
    elif result["matched"] < result["total_tracks"] * 0.5:
        result["verdict"] = "severely_mismatched"

    return result


def _extract_track_names(tracks) -> list:
    """Recursively extract leaf file names from tracks JSON."""
    names = []
    if isinstance(tracks, list):
        for t in tracks:
            if isinstance(t, dict):
                if t.get("type") == "folder" and "children" in t:
                    names.extend(_extract_track_names(t["children"]))
                elif "title" in t:
                    names.append(t["title"])
    return names


# ══════════════════════════════════════════════
# EXECUTE
# ══════════════════════════════════════════════
def execute_normalize(dirs_info: list, db_path="history.db"):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = Path(".local_backups") / f"external_intake_{ts}"
    os.makedirs(backup_dir, exist_ok=True)
    quarantine_dir = Path(str(QUARANTINE_BASE) + f"_{ts}")
    os.makedirs(quarantine_dir, exist_ok=True)

    # Backup DB
    for f in [db_path, db_path + "-shm", db_path + "-wal"]:
        p = Path(f)
        if p.exists(): shutil.copy2(p, backup_dir / p.name)

    conn = sqlite3.connect(db_path); conn.row_factory = sqlite3.Row
    meta_titles = {r["rj_id"]: r["title"] for r in conn.execute("SELECT rj_id, title FROM metadata_cache").fetchall()}

    rollback = []
    stats = {"moved": 0, "quarantined": 0, "db_updated": 0, "errors": 0}

    for info in dirs_info:
        d = Path(info["dir"]); rj_id = info["rj_id"]; action = info["action"]
        if not d.exists(): continue

        try:
            if action == "quarantine":
                dest = quarantine_dir / d.name
                shutil.move(str(d), str(dest))
                rollback.append({"type": "unquarantine", "from": str(dest), "to": str(d)})
                stats["quarantined"] += 1
                conn.execute("DELETE FROM works WHERE rj_id=?", (rj_id,))
                conn.execute("DELETE FROM library_items WHERE rj_id=?", (rj_id,))
                conn.execute("DELETE FROM library_index WHERE rj_id=?", (rj_id,))
                stats["db_updated"] += 3

            elif action in ("needs_rename_top_level", "needs_title_layer"):
                title = meta_titles.get(rj_id) or _extract_title(d.name, rj_id)
                safe_t = safe_name(title)
                new_root = E_ROOT / rj_id
                new_title = new_root / safe_t

                if action == "needs_rename_top_level":
                    os.makedirs(new_title, exist_ok=True)
                    for child in list(d.iterdir()):
                        shutil.move(str(child), str(new_title / child.name))
                    try: d.rmdir()
                    except: pass
                    rollback.append({"type": "undo_rename", "rj": rj_id, "from": str(d), "to": str(new_root)})
                else:
                    os.makedirs(new_title, exist_ok=True)
                    for child in list(d.iterdir()):
                        if child.is_file():
                            shutil.move(str(child), str(new_title / child.name))
                        elif child.is_dir() and child.name != safe_t:
                            shutil.move(str(child), str(new_title / child.name))
                    rollback.append({"type": "undo_layer", "rj": rj_id})
                stats["moved"] += 1

                # Update DB
                conn.execute("UPDATE works SET local_path=? WHERE rj_id=?", (str(new_root), rj_id))
                conn.execute("UPDATE library_items SET folder_path=?, folder_name=?, updated_at=? WHERE rj_id=?",
                             (str(new_root), safe_t, datetime.now().isoformat(), rj_id))
                conn.execute("UPDATE library_index SET work_dir=?, library_path=? WHERE rj_id=?",
                             (str(new_title), str(new_root), rj_id))
                stats["db_updated"] += 3
        except Exception as ex:
            stats["errors"] += 1
            print(f"  ERROR {rj_id}: {ex}")

    conn.commit()
    conn.close()

    with open(backup_dir / "rollback_plan.json", "w", encoding="utf-8") as f:
        json.dump(rollback, f, ensure_ascii=False, indent=2, default=str)

    return stats, str(backup_dir)


def _extract_title(name: str, rj_id: str) -> str:
    m = RJ_RE.search(name)
    if not m: return name
    start = m.end()
    while start < len(name) and name[start] in " 】】】":
        start += 1
    return name[start:].strip() or rj_id


# ══════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--confirm-bulk", action="store_true")
    p.add_argument("--refresh-metadata", action="store_true")
    p.add_argument("--verify-filelist", action="store_true")
    args = p.parse_args()
    if args.execute: args.dry_run = False

    dirs_info, plan = scan_top_dirs()
    print(f"Scanned: {plan['scanned_top_dirs']} dirs, {plan['unique_rj']} unique RJ")

    print(f"  already_normalized: {plan.get('already_normalized',0)}")
    print(f"  needs_rename_top_level: {plan.get('needs_rename_top_level',0)}")
    print(f"  needs_title_layer: {plan.get('needs_title_layer',0)}")
    print(f"  quarantine: {plan.get('quarantine_required',0)}")
    blockers = plan.get("blocker_list", [])
    print(f"  blockers: {plan.get('blockers', 0)}")
    if blockers:
        for b in blockers[:5]: print(f"    - {b}")

    if args.refresh_metadata:
        rj_ids = [info["rj_id"] for info in dirs_info if info["rj_id"] and info["action"] != "quarantine"]
        print(f"\nRefreshing metadata for {len(rj_ids)} RJs...")
        from core.config import ConfigManager
        cfg = ConfigManager.load()
        report = asyncio.run(refresh_metadata(rj_ids, cfg))
        print(f"  refreshed: {report['refreshed']}, failed: {report['failed']}")

    if args.verify_filelist:
        conn = sqlite3.connect("history.db"); conn.row_factory = sqlite3.Row
        mismatch = []
        for info in dirs_info:
            if info["action"] in ("quarantine",) or not info["rj_id"]: continue
            d = Path(info["dir"]) if info["dir"] and Path(info["dir"]).exists() else (E_ROOT / info["rj_id"])
            if not d.exists(): continue
            v = verify_filelist(info["rj_id"], d, conn)
            if v["verdict"] != "ok":
                mismatch.append(v)
        conn.close()
        print(f"\nFilelist verify: {len(mismatch)} mismatches")
        for m in mismatch[:10]:
            print(f"  {m['rj_id']}: {m['verdict']} (missing_audio={len(m['missing_audio'])})")

    if args.execute and args.confirm_bulk and plan.get("can_execute"):
        print("\nEXECUTING...")
        stats, bkp = execute_normalize(dirs_info)
        for k, v in stats.items(): print(f"  {k}: {v}")
        print(f"  backup: {bkp}")
        # Verify integrity
        conn = sqlite3.connect("history.db")
        print(f"  integrity: {conn.execute('PRAGMA integrity_check').fetchone()[0]}")
        conn.close()
    elif args.execute:
        if not args.confirm_bulk:
            print("\nBLOCKED: --confirm-bulk is required for actual organize.")
        else:
            print(f"\nBLOCKED: {plan.get('blockers', 0)} blockers exist. Resolve blockers before execute.")

    # Report
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rpt = Path(".local_backups") / f"external_intake_{ts}"
    os.makedirs(rpt, exist_ok=True)
    with open(rpt / "external_intake_plan.json", "w", encoding="utf-8") as f:
        json.dump({"plan": plan, "dirs": dirs_info[:50]}, f, ensure_ascii=False, indent=2, default=str)
    with open(rpt / "external_intake_summary.txt", "w", encoding="utf-8") as f:
        for k, v in plan.items(): f.write(f"{k}: {v}\n")
    print(f"Report: {rpt}")


if __name__ == "__main__":
    main()
