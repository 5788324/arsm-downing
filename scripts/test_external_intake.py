"""Tests for external_intake.py"""
import sys, os, tempfile, json
from pathlib import Path
sys.path.insert(0, ".")

from tools import external_intake as ext
from tools.external_intake import norm_rj, _classify_dir, safe_name, _extract_track_names, compute_blockers

passed = failed = 0
def check(name, condition):
    global passed, failed
    if condition: passed += 1; print(f"  PASS: {name}")
    else: failed += 1; print(f"  FAIL: {name}")

print("=== External Intake Tests ===\n")
TMP_BASE = Path(".tmp_tests")
TMP_BASE.mkdir(exist_ok=True)

# norm_rj
check("norm_rj pure", norm_rj("RJ01087430") == "RJ01087430")
check("norm_rj with title", norm_rj("RJ01087430 【title】") == "RJ01087430")
check("norm_rj no prefix", norm_rj("01087430") == "RJ01087430")
check("norm_rj brackets", norm_rj("【RJ01087430】title") == "RJ01087430")
check("norm_rj no match", norm_rj("random_folder") == "")

# safe_name
check("safe_name normal", safe_name("test title") == "test title")
check("safe_name special chars", safe_name("test:file<name>") == "testfilename")
check("safe_name truncate", len(safe_name("a" * 100)) <= 80)

# _classify_dir
with tempfile.TemporaryDirectory(dir=TMP_BASE) as td:
    root = Path(td)
    # Pure RJ + subdirs = already_normalized
    d1 = root / "RJ01087430"
    d1.mkdir()
    (d1 / "sub").mkdir()
    c1 = _classify_dir(d1, "RJ01087430")
    check("pure_rj_with_subdirs", c1["action"] == "already_normalized")

    # Pure RJ + only files = needs_title_layer
    d2 = root / "RJ01087431"
    d2.mkdir()
    (d2 / "track01.mp3").write_text("")
    c2 = _classify_dir(d2, "RJ01087431")
    check("pure_rj_needs_layer", c2["action"] == "needs_title_layer")

    # RJ + title top-level = needs_rename
    d3 = root / "RJ01087432 【简体中文版】test"
    d3.mkdir()
    (d3 / "track01.mp3").write_text("")
    c3 = _classify_dir(d3, "RJ01087432")
    check("rj_title_top_level", c3["action"] == "needs_rename_top_level")

    # .part file = quarantine
    d4 = root / "RJ01087433"
    d4.mkdir()
    (d4 / "file.part").write_text("")
    c4 = _classify_dir(d4, "RJ01087433")
    check("part_file_quarantine", c4["action"] == "quarantine")

    # Empty = quarantine
    d5 = root / "RJ01087434"
    d5.mkdir()
    c5 = _classify_dir(d5, "RJ01087434")
    check("empty_quarantine", c5["action"] == "quarantine")

    # No RJ match
    c6 = _classify_dir(Path(td) / "random", "")
    check("no_rj", c6["action"] != "already_normalized")

# _extract_track_names
tracks = [
    {"type": "audio", "title": "track01.mp3"},
    {"type": "audio", "title": "track02.wav"},
    {"type": "folder", "children": [
        {"type": "audio", "title": "inner.mp3"}
    ]}
]
names = _extract_track_names(tracks)
check("extract_leaf_tracks", len(names) == 3)
check("extract_includes_inner", "inner.mp3" in names)
check("extract_includes_root", "track01.mp3" in names)


# blocker / scan_structure semantics
with tempfile.TemporaryDirectory(dir=TMP_BASE) as td:
    old_root = ext.E_ROOT
    ext.E_ROOT = Path(td)
    try:
        ok = ext.E_ROOT / "RJ01087500"
        ok.mkdir()
        (ok / "title").mkdir()
        dirs_info, plan = ext.scan_top_dirs()
        check("no_blockers_count_zero", plan["blockers"] == 0)
        check("no_blockers_can_execute", plan["can_execute"] is True)
        check("scan_structure_has_actions", isinstance(ext.scan_structure().get("actions"), list))

        bad = ext.E_ROOT / "RJ01087501"
        bad.mkdir()
        dirs_info, plan = ext.scan_top_dirs()
        check("empty_dir_blocks_execute", plan["blockers"] >= 1 and plan["can_execute"] is False)
        check("compute_blockers_reports_empty", any("empty" in b for b in compute_blockers(dirs_info)))
    finally:
        ext.E_ROOT = old_root

# scan_top_dirs runs on live E:\arsm (read-only)
from tools.external_intake import scan_top_dirs
dirs_info, plan = scan_top_dirs()
check("scan_returns_dirs", len(dirs_info) > 0)
check("scan_has_unique_rj", plan["unique_rj"] > 0)
check("scan_blockers_is_count", isinstance(plan.get("blockers"), int))
check("scan_no_crashes", True)

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
print(f"Overall: {'PASS' if failed == 0 else 'FAIL'}")
sys.exit(0 if failed == 0 else 1)
