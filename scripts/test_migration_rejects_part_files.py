#!/usr/bin/env python3
"""migration rejects part files."""
import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}\n  migration rejects part files\n{'='*60}\n")
    import core.database as database_module
    from core.migration import MigrationEngine
    from core.models import WorkMetadata

    base = Path(tempfile.gettempdir()).resolve() / 'tmp_test_part'
    src = base / 'src' / 'RJ99804'
    target = base / 'target'
    src.mkdir(parents=True, exist_ok=True)
    target.mkdir(parents=True, exist_ok=True)
    (src / 't1.mp3').write_bytes(b'x' * 100)
    (src / 't1.mp3.part').write_bytes(b'x')
    db_path = base / 'history.db'
    if db_path.exists():
        db_path.unlink()
    database_module.DB_FILE = db_path
    db = database_module.LibraryVault()

    rj = 'RJ99804'
    meta = WorkMetadata(rj_id=rj, title='P', circle='', cv=[], tags=[], price=0, source_url='', dl_count=0, rating=0.0, release_date='', cover_url='')
    db.register(meta, 100, src, status='completed')
    db.upsert_download(f'{rj}:t1', rj, 't1', str(src / 't1.mp3'), 'registered', 100, 100)
    db.commit()

    cand = MigrationEngine(db).get_candidates(str(target))
    assert rj not in {c['rj_id'] for c in cand}, cand
    print('  OK .part rejected')

    shutil.rmtree(base, ignore_errors=True)
    print(f"\n{'='*60}\n  OK passed\n{'='*60}\n")
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(test()))
