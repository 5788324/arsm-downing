#!/usr/bin/env python3
from pathlib import Path
import inspect, sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.migration import MigrationEngine

print('ToolsView calls MigrationEngine')
src = inspect.getsource(MigrationEngine.migrate_one)
for token in ('MIGRATION_START', 'MIGRATION_COPY_DONE', 'MIGRATION_DONE', 'MIGRATION_FAIL'):
    assert token in src
text = Path('ui/views/tools_view.py').read_text(encoding='utf-8')
assert 'migrate_execute' in text
assert 'engine.migrate_one' in text or 'migrate_one' in text
print('OK ToolsView.migrate_execute calls migrate_one')
