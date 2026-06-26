#!/usr/bin/env python3
import inspect, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.migration import MigrationEngine
src = inspect.getsource(MigrationEngine.migrate_one)
for key in ('delete_allowed_after_full_verification', 'migrated_at', 'status', 'source', 'target'):
    assert key in src, key
print('OK cleanup plan schema fields present')
