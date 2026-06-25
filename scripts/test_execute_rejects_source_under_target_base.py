#!/usr/bin/env python3
import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}\n  execute rejects source under target base\n{'='*60}\n")
    from core.database import LibraryVault
    from core.migration import MigrationEngine
    from core.models import WorkMetadata

    base = Path('tmp_hotfix_reject_source').resolve()
    target = base / 'target'
    src = target / 'RJHOTFIX003'
    tgt = target / 'RJHOTFIX003-copy'
    src.mkdir(parents=True, exist_ok=True)
    (src / 't1.mp3').write_bytes(b'x' * 100)

    db = LibraryVault()
    rj = 'RJHOTFIX003'
    meta = WorkMetadata(rj_id=rj, title='T', circle='', cv=[], tags=[], price=0, source_url='', dl_count=0, rating=0.0, release_date='', cover_url='')
    db.register(meta, 100, src, status='completed')
    db.upsert_download(f'{rj}:t1', rj, 't1', str(src / 't1.mp3'), 'registered', 100, 100)
    db.commit()

    result = MigrationEngine(db).validate_migration_request(rj, str(src), str(tgt), str(target))
    assert not result['success'], result
    assert result['reason'] == 'source_under_target_base', result
    print(f"  OK reject reason={result['reason']}")

    db.conn.execute('DELETE FROM works WHERE rj_id=?', (rj,))
    db.conn.execute('DELETE FROM downloads WHERE rj_id=?', (rj,))
    db.commit()
    shutil.rmtree(base, ignore_errors=True)
    print(f"\n{'='*60}\n  OK passed\n{'='*60}\n")
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(test()))
