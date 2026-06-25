#!/usr/bin/env python3
"""verify migrated work success."""
import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}\n  verify migrated work success\n{'='*60}\n")
    import core.database as database_module
    from core.migration import MigrationEngine
    from core.models import WorkMetadata

    base = Path(tempfile.gettempdir()).resolve() / 'tmp_test_verify_success'
    src = base / 'src' / 'RJ99968'
    target = base / 'target'
    tgt = target / 'RJ99968'
    src.mkdir(parents=True, exist_ok=True)
    target.mkdir(parents=True, exist_ok=True)
    (src / 't1.mp3').write_bytes(b'x' * 100)
    db_path = base / 'history.db'
    if db_path.exists():
        db_path.unlink()
    database_module.DB_FILE = db_path
    db = database_module.LibraryVault()

    rj = 'RJ99968'
    meta = WorkMetadata(rj_id=rj, title='T', circle='', cv=[], tags=[], price=0, source_url='', dl_count=0, rating=0.0, release_date='', cover_url='')
    db.register(meta, 100, src, status='completed')
    db.upsert_download(f'{rj}:t1', rj, 't1', str(src / 't1.mp3'), 'registered', 100, 100)
    db.commit()

    engine = MigrationEngine(db)
    res = engine.migrate_one(rj, str(src), str(tgt), target_base=str(target))
    assert res['success'], res
    verify = engine.verify_migrated_work(rj, str(target), source_roots=[str(base / 'src')])
    assert verify['success'], verify
    print(f"  OK verified {verify['work_path']}")

    shutil.rmtree(base, ignore_errors=True)
    print(f"\n{'='*60}\n  OK passed\n{'='*60}\n")
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(test()))
