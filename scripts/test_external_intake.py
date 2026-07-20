#!/usr/bin/env python3
"""Compatibility entry point for the portable external-intake test suite."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    suite = unittest.defaultTestLoader.discover(
        str(REPO_ROOT / "tests"), pattern="test_external_intake_*.py"
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
