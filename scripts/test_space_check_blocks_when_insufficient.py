#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.migration import MigrationEngine
orig = MigrationEngine._resolve_path
orig_du = __import__('shutil').disk_usage
class DU:
    total=0; used=0; free=100
try:
    import shutil
    shutil.disk_usage = lambda _: DU
    res = MigrationEngine.get_disk_space_check('.', 1000, headroom_ratio=0.1)
    assert not res['enough_space']
    print('OK insufficient space blocks')
finally:
    shutil.disk_usage = orig_du
