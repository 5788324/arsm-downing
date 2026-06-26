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
        return {'success': False, 'updated': 0, 'error': 'forced'}

tmp = Path(f'tmp_test_db_fail_{uuid4().hex}').resolve()
shutil.rmtree(tmp, ignore_errors=True)
tmp.mkdir(parents=True, exist_ok=True)
orig_rename = os.rename
os.rename = fake_rename
try:
    src = tmp / 'src' / 'RJTEST6'
    dst = tmp / 'dst' / 'RJTEST6'
    src.mkdir(parents=True, exist_ok=True)
    (src / 'a.bin').write_bytes(b'abc')
    db = FakeDB()
    db.conn.execute("INSERT INTO works VALUES (?,?,?,?,?)", ('RJTEST6', 'T', str(src), 'completed', 3))
    db.conn.commit()
    res = MigrationEngine(db).migrate_one('RJTEST6', str(src), str(dst), delete_source=False, target_base=str(tmp / 'dst'))
    assert not res['success']
    assert src.exists()
    print('OK no source delete on db failure')
finally:
    os.rename = orig_rename
    shutil.rmtree(tmp, ignore_errors=True)
