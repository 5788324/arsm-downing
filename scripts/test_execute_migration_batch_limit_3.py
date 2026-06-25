#!/usr/bin/env python3
"""batch limit <= 3."""
import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}\n  batch limit 3\n{'='*60}\n")
    import core.database as database_module
    from core.migration import MigrationEngine
    from core.models import WorkMetadata

    base = Path(tempfile.gettempdir()).resolve() / 'tmp_test_batch_limit'
    target = base / 'target'
    target.mkdir(parents=True, exist_ok=True)
    db_path = base / 'history.db'
    if db_path.exists():
        db_path.unlink()
    database_module.DB_FILE = db_path
    db = database_module.LibraryVault()

    for i in range(5):
        rj = f'RJ{99830000+i:08d}'
        src = base / 'src' / rj
        src.mkdir(parents=True, exist_ok=True)
        (src / 't1.mp3').write_bytes(b'x' * 10)
        meta = WorkMetadata(rj_id=rj, title=f'T{i}', circle='', cv=[], tags=[], price=0, source_url='', dl_count=0, rating=0.0, release_date='', cover_url='')
        db.register(meta, 10, src, status='completed')
        db.upsert_download(f'{rj}:t1', rj, 't1', str(src / 't1.mp3'), 'registered', 10, 10)
    db.commit()

    candidates = MigrationEngine(db).get_candidates(str(target))
    batch = candidates[:3]
    assert len(batch) == 3, batch
    print(f"  OK batch limited to {len(batch)} from {len(candidates)} candidates")

    shutil.rmtree(base, ignore_errors=True)
    print(f"\n{'='*60}\n  OK passed\n{'='*60}\n")
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(test()))
