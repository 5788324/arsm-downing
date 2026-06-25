#!/usr/bin/env python3
import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}\n  candidate already under output_dir skipped\n{'='*60}\n")
    import core.database as database_module
    from core.migration import MigrationEngine
    from core.models import WorkMetadata

    base = Path(tempfile.gettempdir()).resolve() / 'tmp_hotfix_already'
    target = base / 'target'
    src = target / 'RJHOTFIX002'
    src.mkdir(parents=True, exist_ok=True)
    (src / 't1.mp3').write_bytes(b'x' * 100)
    db_path = base / 'history.db'
    if db_path.exists():
        db_path.unlink()
    database_module.DB_FILE = db_path
    db = database_module.LibraryVault()

    rj = 'RJHOTFIX002'
    meta = WorkMetadata(rj_id=rj, title='T', circle='', cv=[], tags=[], price=0, source_url='', dl_count=0, rating=0.0, release_date='', cover_url='')
    db.register(meta, 100, src, status='verified')
    db.upsert_download(f'{rj}:t1', rj, 't1', str(src / 't1.mp3'), 'registered', 100, 100)
    db.commit()

    dry = MigrationEngine(db).dry_run(str(target))
    assert dry['candidate_count'] == 0, dry
    assert dry['skipped_already_on_target'] == 1, dry
    print(f"  OK skipped_already_on_target={dry['skipped_already_on_target']}")

    shutil.rmtree(base, ignore_errors=True)
    print(f"\n{'='*60}\n  OK passed\n{'='*60}\n")
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(test()))
