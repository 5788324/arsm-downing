"""External intake — scan, plan, normalize E:\arsm file tree.
Usage:
  python tools/external_intake.py --dry-run
  python tools/external_intake.py --execute
"""
import sqlite3, json, os, sys, re, shutil
from pathlib import Path
from datetime import datetime
from collections import defaultdict

try: sys.stdout.reconfigure(encoding='utf-8')
except: pass

E_ROOT = Path(r"E:\arsm")
QUARANTINE_ROOT = Path(r"E:\arsm_quarantine_external")
RJ_RE = re.compile(r'(?:RJ)?(\d{6,8})', re.IGNORECASE)

def normalize_rj(name: str) -> str:
    m = RJ_RE.search(name)
    if m: return f"RJ{int(m.group(1)):08d}"
    return ""

def get_title_from_dir(d: Path) -> str:
    """Extract title portion from a directory name like 'RJ01087430 title...'."""
    name = d.name
    m = RJ_RE.search(name)
    if not m: return name
    # Remove the RJ portion
    start = m.end()
    # Skip any brackets/punctuation after RJ
    while start < len(name) and name[start] in " 】】】":
        start += 1
    title = name[start:].strip()
    return title or name

def scan_structure():
    """Read-only scan of E:\arsm. Returns plan."""
    plan = {
        "scanned_top_dirs": 0, "unique_rj": 0,
        "already_normalized": 0, "needs_rename_top_level": 0,
        "needs_title_layer": 0, "duplicate_rj": 0,
        "metadata_missing": 0, "quarantine_required": 0,
        "actions": [],
    }
    rj_seen = {}  # rj_id -> first_dir

    if not E_ROOT.exists():
        return plan

    for d in sorted(E_ROOT.iterdir()):
        if not d.is_dir(): continue
        plan["scanned_top_dirs"] += 1

        rj_id = normalize_rj(d.name)
        if not rj_id:
            plan["quarantine_required"] += 1
            plan["actions"].append({"dir": str(d), "action": "quarantine", "reason": "no_rj_match"})
            continue

        # Check duplicates
        if rj_id in rj_seen:
            plan["duplicate_rj"] += 1
            plan["actions"].append({"dir": str(d), "action": "quarantine", "reason": f"duplicate_rj: {rj_id}, winner={rj_seen[rj_id]}"})
            continue
        rj_seen[rj_id] = d

        # Check structure
        action = analyze_dir(d, rj_id)
        plan["actions"].append(action)
        plan[action["action"]] = plan.get(action["action"], 0) + 1

    plan["unique_rj"] = len(rj_seen)
    return plan


def analyze_dir(d: Path, rj_id: str) -> dict:
    """Determine what needs to be done for one directory."""
    name = d.name
    is_pure_rj = name == rj_id
    title = get_title_from_dir(d)
    has_subdirs = any(sub.is_dir() for sub in d.iterdir()) if d.is_dir() else False
    has_files_at_root = any(sub.is_file() for sub in d.iterdir()) if d.is_dir() else False

    result = {"dir": str(d), "rj_id": rj_id, "name": name,
              "is_pure_rj": is_pure_rj, "title": title,
              "has_subdirs": has_subdirs, "has_files_at_root": has_files_at_root}

    if is_pure_rj and has_subdirs:
        # Already looks good: E:\arsm\RJxxxx\subdirs...
        result["action"] = "already_normalized"
    elif is_pure_rj and not has_subdirs and has_files_at_root:
        # Pure RJ dir but files at root: needs title layer
        result["action"] = "needs_title_layer"
    elif not is_pure_rj:
        # Has title in name: needs rename to RJxxxx + title subdir
        result["action"] = "needs_rename_top_level"
    else:
        result["action"] = "already_normalized"

    return result


def execute_plan(plan: dict, db_path: str = "history.db"):
    """Execute normalization. Must have backup first."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = Path(".local_backups") / f"external_intake_{ts}"
    os.makedirs(backup_dir, exist_ok=True)
    quarantine_dir = Path(str(QUARANTINE_ROOT) + f"_{ts}")
    os.makedirs(quarantine_dir, exist_ok=True)

    # Backup DB
    shutil.copy2(db_path, backup_dir / "history.before_intake.db")
    for ext in [".db-shm", ".db-wal"]:
        p = Path(db_path + ext)
        if p.exists(): shutil.copy2(p, backup_dir / p.name)

    # DB connection
    conn = sqlite3.connect(db_path); conn.row_factory = sqlite3.Row
    # Build metadata lookup
    meta_titles = {}
    for row in conn.execute("SELECT rj_id, title FROM metadata_cache"):
        meta_titles[row["rj_id"]] = row["title"]

    rollback = []
    executed = {"would_update_db": 0, "would_move_dirs": 0, "quarantined": 0,
                "needs_rename_top_level": 0, "needs_title_layer": 0}

    for a in plan["actions"]:
        action = a["action"]
        d = Path(a["dir"])
        rj_id = a["rj_id"]

        if action == "quarantine":
            if not d.exists(): continue
            dest = quarantine_dir / d.name
            shutil.move(str(d), str(dest))
            rollback.append({"type": "unquarantine", "from": str(dest), "to": str(d)})
            executed["quarantined"] += 1
            # Remove from DB
            conn.execute("DELETE FROM works WHERE rj_id=?", (rj_id,))
            conn.execute("DELETE FROM library_items WHERE rj_id=?", (rj_id,))
            conn.execute("DELETE FROM library_index WHERE rj_id=?", (rj_id,))
            executed["would_update_db"] += 3

        elif action == "needs_rename_top_level":
            # Get metadata title
            title = meta_titles.get(rj_id) or a.get("title", rj_id)
            safe_title = re.sub(r'[<>:"/\\|?*]', '', title)[:80]

            new_root = E_ROOT / rj_id
            new_title_dir = new_root / safe_title

            if not new_root.exists():
                os.makedirs(new_title_dir, exist_ok=True)
                # Move children into title dir
                for child in list(d.iterdir()):
                    shutil.move(str(child), str(new_title_dir / child.name))
                # Remove old dir (now empty)
                try: d.rmdir()
                except: pass
                rollback.append({"type": "unrename", "from": str(new_root), "to": str(d)})
                executed["needs_rename_top_level"] += 1

                # Update DB
                conn.execute("UPDATE works SET local_path=? WHERE rj_id=?", (str(new_root), rj_id))
                conn.execute("UPDATE library_items SET folder_path=? WHERE rj_id=?", (str(new_root), rj_id))
                conn.execute("UPDATE library_index SET work_dir=? WHERE rj_id=?", (str(new_title_dir), rj_id))
                executed["would_update_db"] += 3

        elif action == "needs_title_layer":
            title = meta_titles.get(rj_id) or a.get("title", rj_id)
            safe_title = re.sub(r'[<>:"/\\|?*]', '', title)[:80]
            new_title_dir = d / safe_title

            os.makedirs(new_title_dir, exist_ok=True)
            for child in list(d.iterdir()):
                if child.is_file():
                    shutil.move(str(child), str(new_title_dir / child.name))
                elif child.is_dir() and child.name != safe_title:
                    shutil.move(str(child), str(new_title_dir / child.name))
            rollback.append({"type": "unlayer", "from": str(new_title_dir), "to": str(d)})
            executed["needs_title_layer"] += 1

    conn.commit()
    conn.close()

    # Write rollback
    with open(backup_dir / "rollback_plan.json", "w", encoding="utf-8") as f:
        json.dump(rollback, f, ensure_ascii=False, indent=2)

    return executed


def main():
    dry = "--execute" not in sys.argv

    print("=" * 60)
    print(f"External Intake {'DRY-RUN' if dry else 'EXECUTE'}")
    print("=" * 60)

    plan = scan_structure()
    print(f"\nScanned: {plan['scanned_top_dirs']} dirs, {plan['unique_rj']} unique RJ")
    print(f"  already_normalized: {plan['already_normalized']}")
    print(f"  needs_rename_top_level: {plan['needs_rename_top_level']}")
    print(f"  needs_title_layer: {plan['needs_title_layer']}")
    print(f"  duplicate_rj: {plan['duplicate_rj']}")
    print(f"  quarantine_required: {plan['quarantine_required']}")

    if dry:
        print("\nActions (first 10):")
        for a in plan["actions"][:10]:
            print(f"  [{a['action']}] {a.get('name', a.get('dir',''))[:60]}")
        print("\nUse --execute to apply.")
    else:
        result = execute_plan(plan)
        print("\nExecuted:")
        for k, v in result.items():
            if v > 0: print(f"  {k}: {v}")
        print("\nDone.")

    # Write report
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rpt = Path(".local_backups") / f"external_intake_{ts}"
    os.makedirs(rpt, exist_ok=True)
    with open(rpt / "external_intake_plan.json", "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2, default=str)
    with open(rpt / "external_intake_summary.txt", "w", encoding="utf-8") as f:
        for k, v in plan.items():
            if k != "actions":
                f.write(f"{k}: {v}\n")
    print(f"Report: {rpt}")


if __name__ == "__main__":
    main()
