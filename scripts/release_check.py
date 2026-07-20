from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.version import APP_NAME, APP_VERSION
FORBIDDEN_STATE = ("history.db", "config.json", "queue.json")


def main() -> int:
    parser = argparse.ArgumentParser(description="ARSM release-candidate checks")
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()

    failures: list[str] = []
    for name in FORBIDDEN_STATE:
        if (ROOT / name).exists():
            failures.append(f"active state file exists in repository: {name}")

    spec = ROOT / "ARSMSuite.spec"
    if not spec.exists():
        failures.append("missing ARSMSuite.spec")

    if not (ROOT / "packaging" / "windows_version_info.txt").exists():
        failures.append("missing Windows version metadata")

    test_returncode = None
    if not args.skip_tests and not failures:
        test_returncode = subprocess.call(
            [sys.executable, "-m", "pytest", "-q"], cwd=ROOT
        )
        if test_returncode:
            failures.append(f"pytest failed with exit code {test_returncode}")

    payload = {
        "app": APP_NAME,
        "version": APP_VERSION,
        "python": sys.version.split()[0],
        "pytest_returncode": test_returncode,
        "ready": not failures,
        "failures": failures,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
