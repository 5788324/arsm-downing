#!/usr/bin/env python3
import os, sqlite3, sys, shutil
from pathlib import Path
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.migration import MigrationEngine

def fake_rename(src, dst):
    src_p = Path(src)
    dst_p = Path(dst)
    dst_p.parent.mkdir(parents=True, exist_ok=True)
    if src_p.is_dir():
        shutil.copytree(src_p, dst_p, dirs_exist_ok=True)
        shutil.rmtree(src_p, ignore_errors=True)
    else:
        shutil.copy2(src_p, dst_p)
        src_p.unlink()


class FakeDB:
    def __init__(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("CREATE TABLE works (rj_id TEXT PRIMARY KEY, title TEXT, local_path TEXT, status TEXT, size_bytes INTEGER)")
        self.conn.execute("CREATE TABLE downloads (id TEXT PRIMARY KEY, rj_id TEXT, local_path TEXT, status TEXT)")
        self.conn.execute("CREATE TABLE library_index (rj_id TEXT, library_path TEXT, work_dir TEXT, status TEXT)")
    def get_safe_migratable_works(self):
        return [dict(x) for x in self.conn.execute("SELECT rj_id, title, local_path, status, size_bytes FROM works").fetchall()]
    def move_work_to_path(self, rj_id, old_path, new_path):
        self.conn.execute("UPDATE works SET local_path=? WHERE rj_id=?", (new_path, rj_id))
        self.conn.execute("UPDATE downloads SET local_path=REPLACE(local_path, ?, ?) WHERE rj_id=?", (old_path, new_path, rj_id))
        self.conn.execute("UPDATE library_index SET work_dir=?, library_path=? WHERE rj_id=?", (new_path, str(Path(new_path).parent), rj_id))
        self.conn.commit()
        return {'success': True, 'updated': 2, 'error': ''}

root = Path(f'tmp_test_verify_preserved_{uuid4().hex}').resolve()
shutil.rmtree(root, ignore_errors=True)
root.mkdir(parents=True, exist_ok=True)
orig_cleanup = MigrationEngine.CLEANUP_PLAN_FILE
orig_rename = os.rename
MigrationEngine.CLEANUP_PLAN_FILE = root / 'cleanup.jsonl'
os.rename = fake_rename
try:
    src = root / 'old' / 'RJTEST5'
    dst = root / 'E' / 'RJTEST5'
    src.mkdir(parents=True, exist_ok=True)
    (src / 'a.bin').write_bytes(b'abc')
    db = FakeDB()
    db.conn.execute("INSERT INTO works VALUES (?,?,?,?,?)", ('RJTEST5', 'T', str(src), 'completed', 3))
    db.conn.execute("INSERT INTO downloads VALUES (?,?,?,?)", ('1', 'RJTEST5', str(src / 'a.bin'), 'completed'))
    db.conn.execute("INSERT INTO library_index VALUES (?,?,?,?)", ('RJTEST5', str(src.parent), str(src), 'found'))
    db.conn.commit()
    MigrationEngine(db).migrate_one('RJTEST5', str(src), str(dst), delete_source=False, target_base=str(root / 'E'))
    result = MigrationEngine(db).verify_migrated_work('RJTEST5', str(root / 'E'), source_roots=[str(root / 'old')])
    assert result['success']
    assert result['source_preserved']
    assert result['cleanup_plan_present']
    print('OK verify accepts preserved source')
finally:
    os.rename = orig_rename
    MigrationEngine.CLEANUP_PLAN_FILE = orig_cleanup
    shutil.rmtree(root, ignore_errors=True)
