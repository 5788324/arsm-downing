#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.migration import MigrationEngine
res = MigrationEngine.get_disk_space_check('.', 1000, headroom_ratio=0.1)
assert res['headroom_required_bytes'] == 1100
print('OK headroom calculation works')
