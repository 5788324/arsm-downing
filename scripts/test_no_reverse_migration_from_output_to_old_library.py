#!/usr/bin/env python3
import asyncio
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}\n  no reverse migration from output to old library\n{'='*60}\n")
    import core.database as database_module
    from ui.views.tools_view import ToolsView
    from core.models import WorkMetadata

    base = Path(tempfile.gettempdir()).resolve() / 'tmp_hotfix_reverse'
    target = base / 'target'
    old1 = base / 'old1'
    src = target / 'RJHOTFIX007'
    for p in (target, old1, src):
        p.mkdir(parents=True, exist_ok=True)
    (src / 't1.mp3').write_bytes(b'x' * 100)
    db_path = base / 'history.db'
    if db_path.exists():
        db_path.unlink()
    database_module.DB_FILE = db_path
    db = database_module.LibraryVault()

    rj = 'RJHOTFIX007'
    meta = WorkMetadata(rj_id=rj, title='T', circle='', cv=[], tags=[], price=0, source_url='', dl_count=0, rating=0.0, release_date='', cover_url='')
    db.register(meta, 100, src, status='completed')
    db.upsert_download(f'{rj}:t1', rj, 't1', str(src / 't1.mp3'), 'registered', 100, 100)
    db.commit()

    cfg = SimpleNamespace(output_dir=str(target), library_paths=[str(old1), str(target)])
    ctrl = SimpleNamespace(config=cfg, db=db)

    logs = []
    tv = object.__new__(ToolsView)
    tv.app_controller = ctrl
    tv.log = lambda message, color='white': logs.append(message)

    ToolsView.migrate_dry_run(tv, None)
    assert any('candidate_count=0' in x for x in logs), logs
    assert any('skipped_already_on_target=1' in x for x in logs), logs
    assert not any('target: ' + str(old1) in x for x in logs), logs
    print('  OK reverse migration blocked in dry-run')

    shutil.rmtree(base, ignore_errors=True)
    print(f"\n{'='*60}\n  OK passed\n{'='*60}\n")
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(test()))
