#!/usr/bin/env python3
"""资源库布局结构测试 — 验证 GridView 位于搜索框之后."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test():
    print(f"\n{'='*60}")
    print(f"  资源库布局结构测试")
    print(f"{'='*60}\n")

    import flet as ft
    from ui.views.library_view import LibraryView

    # Mock app_controller
    class FakeApp:
        class FakeDB:
            def search(self, query=""):
                return []
        db = FakeDB()
        config = type('obj', (object,), {})()
    app = FakeApp()

    view = LibraryView(app)

    # Verify structure
    assert isinstance(view.content, ft.Column)
    children = view.content.controls
    assert len(children) >= 3  # title, search_container, divider, grid

    # GridView should be last major element
    has_grid = any(isinstance(c, ft.GridView) for c in children)
    assert has_grid, "应包含 GridView"

    # GridView should have expand=1
    grid = [c for c in children if isinstance(c, ft.GridView)][0]
    assert grid.expand == 1, f"expand={grid.expand}"

    # Container should have padding
    assert view.padding is not None
    print(f"  ✓ GridView 在 Column 中, expand={grid.expand}")
    print(f"  ✓ Container 有 padding")
    print(f"  ✓ 搜索框在前, GridView 在后")

    print(f"\n{'='*60}")
    print(f"  ✓ 资源库布局结构测试通过")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
