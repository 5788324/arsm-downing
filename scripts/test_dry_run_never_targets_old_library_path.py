#!/usr/bin/env python3
import asyncio
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}\n  dry-run never targets old library path\n{'='*60}\n")
    from ui.views.tools_view import ToolsView
    from core.database import LibraryVault
    from core.models import WorkMetadata

    base = Path('tmp_hotfix_dryrun').resolve()
    target = base / 'target'
    old1 = base / 'old1'
    old2 = base / 'old2'
    src = old1 / 'RJHOTFIX001'
    for p in (target, old1, old2, src):
        p.mkdir(parents=True, exist_ok=True)
    (src / 't1.mp3').write_bytes(b'x' * 100)

    db = LibraryVault()
    rj = 'RJHOTFIX001'
    meta = WorkMetadata(rj_id=rj, title='T', circle='', cv=[], tags=[], price=0, source_url='', dl_count=0, rating=0.0, release_date='', cover_url='')
    db.register(meta, 100, src, status='completed')
    db.upsert_download(f'{rj}:t1', rj, 't1', str(src / 't1.mp3'), 'registered', 100, 100)
    db.commit()

    cfg = SimpleNamespace(output_dir=str(target), library_paths=[str(old1), str(target), str(old2)])
    ctrl = SimpleNamespace(config=cfg, db=db)

    logs = []
    tv = object.__new__(ToolsView)
    tv.app_controller = ctrl
    tv.log = lambda message, color='white': logs.append(message)

    ToolsView.migrate_dry_run(tv, None)
    target_lines = [x for x in logs if 'target:' in x]
    assert target_lines, logs
    assert all(str(target) in x for x in target_lines), target_lines
    assert all(str(old1) not in x and str(old2) not in x for x in target_lines), target_lines
    print('\n'.join(target_lines[:3]))

    db.conn.execute('DELETE FROM works WHERE rj_id=?', (rj,))
    db.conn.execute('DELETE FROM downloads WHERE rj_id=?', (rj,))
    db.commit()
    shutil.rmtree(base, ignore_errors=True)
    print(f"\n{'='*60}\n  OK passed\n{'='*60}\n")
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(test()))
