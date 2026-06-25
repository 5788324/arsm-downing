#!/usr/bin/env python3
import asyncio
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}\n  toolsview dry-run shows correct source to target\n{'='*60}\n")
    import core.database as database_module
    from ui.views.tools_view import ToolsView
    from core.models import WorkMetadata

    base = Path(tempfile.gettempdir()).resolve() / 'tmp_hotfix_tv'
    target = base / 'target'
    old1 = base / 'old1'
    src = old1 / 'RJHOTFIX006'
    for p in (target, old1, src):
        p.mkdir(parents=True, exist_ok=True)
    (src / 't1.mp3').write_bytes(b'x' * 100)
    db_path = base / 'history.db'
    if db_path.exists():
        db_path.unlink()
    database_module.DB_FILE = db_path
    db = database_module.LibraryVault()

    rj = 'RJHOTFIX006'
    meta = WorkMetadata(rj_id=rj, title='T', circle='', cv=[], tags=[], price=0, source_url='', dl_count=0, rating=0.0, release_date='', cover_url='')
    db.register(meta, 100, src, status='verified')
    db.upsert_download(f'{rj}:t1', rj, 't1', str(src / 't1.mp3'), 'registered', 100, 100)
    db.commit()

    cfg = SimpleNamespace(output_dir=str(target), library_paths=[str(old1), str(target)])
    ctrl = SimpleNamespace(config=cfg, db=db)

    logs = []
    tv = object.__new__(ToolsView)
    tv.app_controller = ctrl
    tv.log = lambda message, color='white': logs.append(message)

    ToolsView.migrate_dry_run(tv, None)
    source_lines = [x for x in logs if 'source:' in x]
    target_lines = [x for x in logs if 'target:' in x]
    assert len(source_lines) == 1, source_lines
    assert len(target_lines) == 1, target_lines
    assert str(src) in source_lines[0], source_lines
    assert str(target / src.name) in target_lines[0], target_lines
    print(source_lines[0])
    print(target_lines[0])

    shutil.rmtree(base, ignore_errors=True)
    print(f"\n{'='*60}\n  OK passed\n{'='*60}\n")
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(test()))
