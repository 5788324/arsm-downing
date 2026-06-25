#!/usr/bin/env python3
import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}\n  verify uses works.local_path not library_paths last\n{'='*60}\n")
    from core.database import LibraryVault
    from core.migration import MigrationEngine
    from core.models import WorkMetadata

    base = Path('tmp_hotfix_verify').resolve()
    target = base / 'target'
    old1 = base / 'old1'
    old2 = base / 'old2'
    src = old1 / 'RJHOTFIX005'
    target_work = target / 'RJHOTFIX005'
    for p in (target, old1, old2, src, target_work):
        p.mkdir(parents=True, exist_ok=True)
    (target_work / 't1.mp3').write_bytes(b'x' * 100)

    db = LibraryVault()
    rj = 'RJHOTFIX005'
    meta = WorkMetadata(rj_id=rj, title='T', circle='', cv=[], tags=[], price=0, source_url='', dl_count=0, rating=0.0, release_date='', cover_url='')
    db.register(meta, 100, target_work, status='completed')
    db.upsert_download(f'{rj}:t1', rj, 't1', str(target_work / 't1.mp3'), 'registered', 100, 100)
    db.commit()

    result = MigrationEngine(db).verify_migrated_work(rj, str(target), [str(old1), str(old2)])
    assert result['success'], result
    assert result['work_on_target'], result
    print(f"  OK verified path={result['work_path']}")

    db.conn.execute('DELETE FROM works WHERE rj_id=?', (rj,))
    db.conn.execute('DELETE FROM downloads WHERE rj_id=?', (rj,))
    db.commit()
    shutil.rmtree(base, ignore_errors=True)
    print(f"\n{'='*60}\n  OK passed\n{'='*60}\n")
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(test()))
