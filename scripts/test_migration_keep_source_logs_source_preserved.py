#!/usr/bin/env python3
import inspect, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.migration import MigrationEngine
src = inspect.getsource(MigrationEngine.migrate_one)
assert 'MIGRATION_SOURCE_PRESERVED' in src
assert 'source_preserved=True' in src
assert 'cleanup_required=True' in src
print('OK source preserved logging exists')
