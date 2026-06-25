#!/usr/bin/env python3
"""migration candidates completed/verified only."""
import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}\n  migration candidates completed/verified only\n{'='*60}\n")
    import core.database as database_module
    from core.migration import MigrationEngine
    from core.models import WorkMetadata

    base = Path(tempfile.gettempdir()).resolve() / 'tmp_test_candidates'
    target = base / 'target'
    safe_src = base / 'src' / 'RJ99801'
    bad_src = base / 'src' / 'RJ99802'
    for p in (target, safe_src, bad_src):
        p.mkdir(parents=True, exist_ok=True)
    (safe_src / 't1.mp3').write_bytes(b'x' * 100)
    (bad_src / 't1.mp3').write_bytes(b'x' * 100)
    db_path = base / 'history.db'
    if db_path.exists():
        db_path.unlink()
    database_module.DB_FILE = db_path
    db = database_module.LibraryVault()

    safe_rj = 'RJ99801'
    bad_rj = 'RJ99802'
    safe_meta = WorkMetadata(rj_id=safe_rj, title='Safe', circle='', cv=[], tags=[], price=0, source_url='', dl_count=0, rating=0.0, release_date='', cover_url='')
    bad_meta = WorkMetadata(rj_id=bad_rj, title='Bad', circle='', cv=[], tags=[], price=0, source_url='', dl_count=0, rating=0.0, release_date='', cover_url='')
    db.register(safe_meta, 100, safe_src, status='completed')
    db.upsert_download(f'{safe_rj}:t1', safe_rj, 't1', str(safe_src / 't1.mp3'), 'registered', 100, 100)
    db.register(bad_meta, 100, bad_src, status='prepared')
    db.upsert_download(f'{bad_rj}:t1', bad_rj, 't1', str(bad_src / 't1.mp3'), 'queued', 0, 100)
    db.commit()

    engine = MigrationEngine(db)
    safe = db.get_safe_migratable_works()
    safe_ids = {w['rj_id'] for w in safe}
    assert safe_rj in safe_ids, safe_ids
    assert bad_rj not in safe_ids, safe_ids
    candidates = engine.get_candidates(str(target))
    cand_ids = {c['rj_id'] for c in candidates}
    assert safe_rj in cand_ids, cand_ids
    assert bad_rj not in cand_ids, cand_ids
    print(f"  OK safe candidates={cand_ids}")

    shutil.rmtree(base, ignore_errors=True)
    print(f"\n{'='*60}\n  OK passed\n{'='*60}\n")
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(test()))
