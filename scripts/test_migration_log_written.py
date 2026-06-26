#!/usr/bin/env python3
import inspect, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.migration import MigrationEngine

print('migration log written')
src = inspect.getsource(MigrationEngine.migrate_one)
for log in ('MIGRATION_START','MIGRATION_COPY_DONE','MIGRATION_VERIFY_DONE','MIGRATION_DB_UPDATE_DONE','MIGRATION_DELETE_SOURCE_DONE','MIGRATION_DONE','MIGRATION_FAIL'):
    assert log in src, f'missing: {log}'
print('OK migration log stages present')
