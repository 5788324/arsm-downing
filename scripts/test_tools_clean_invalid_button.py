import asyncio
import sys
from pathlib import Path


async def test():
    print("\n" + "=" * 60)
    print("  ToolsView 队列清理安全语义检查")
    print("=" * 60 + "\n")
    src = Path("ui/views/tools_view.py").read_text(encoding="utf-8")
    assert "clean_queue" in src, "源码缺 clean_queue"
    assert "预览队列清理" in src, "源码缺预览语义"
    assert "preview_queue_cleanup" in src, "未接入安全预览服务"
    assert "DELETE FROM downloads" not in src, "ToolsView 不应直接删除 downloads"
    assert 'execute("VACUUM")' not in src, "ToolsView 不应直接 VACUUM"
    print("  ✓ 队列清理为只读预览，ToolsView 无直接 DELETE/VACUUM")
    print("\n" + "=" * 60)
    print("  ✓ 通过")
    print("=" * 60 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
