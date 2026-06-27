#!/usr/bin/env python3
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.unfinished_closeout import build_unfinished_closeout_plan, write_closeout_artifacts


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python scripts/rc9_1_generate_unfinished_closeout_plan.py <output_root>")
        return 2

    output_root = Path(sys.argv[1])
    plan = build_unfinished_closeout_plan(Path("history.db"))
    artifacts = write_closeout_artifacts(output_root, plan)
    print(json.dumps({
        "counts": plan["counts"],
        "artifacts": artifacts,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
