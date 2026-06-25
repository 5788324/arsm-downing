#!/usr/bin/env python3
import asyncio
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}\n  migration target uses output_dir\n{'='*60}\n")
    from ui.views.tools_view import ToolsView

    base = Path('tmp_hotfix_target').resolve()
    target = base / 'target'
    old1 = base / 'old1'
    old2 = base / 'old2'
    for p in (target, old1, old2):
        p.mkdir(parents=True, exist_ok=True)

    cfg = SimpleNamespace(output_dir=str(target), library_paths=[str(old1), str(target), str(old2)])
    ctrl = SimpleNamespace(config=cfg)

    logs = []
    tv = object.__new__(ToolsView)
    tv.app_controller = ctrl
    tv.log = lambda message, color='white': logs.append(message)

    resolved = ToolsView.resolve_migration_target(tv)
    assert resolved == target.resolve(), (resolved, target.resolve())
    assert any('MIGRATION_TARGET_RESOLVED' in x for x in logs), logs
    print(f"  OK resolved target: {resolved}")

    shutil.rmtree(base, ignore_errors=True)
    print(f"\n{'='*60}\n  OK passed\n{'='*60}\n")
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(test()))
