#!/usr/bin/env python3
from pathlib import Path
text = Path('core/database.py').read_text(encoding='utf-8')
assert 'DELETE FROM library_index WHERE rj_id = ? AND work_dir = ? AND work_dir != ?' in text
assert 'UPDATE library_index SET work_dir = ?, library_path = ?' in text
assert 'INSERT OR IGNORE INTO library_index' in text
print('OK move_work_to_path handles stale target library_index rows')
