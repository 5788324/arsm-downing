#!/usr/bin/env python3
"""Portable works-status display diagnostic."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    from core.database import LibraryVault
    from core.models import WorkMetadata
    from ui.views.library_view import STATUS_LABELS

    print(f"\n{'='*60}\n  仓库状态显示测试\n{'='*60}\n")
    with TemporaryDirectory(prefix="arsm-library-status-") as temp:
        with LibraryVault(Path(temp) / "history.db") as db:
            for rj, title, status in (
                ("RJ00088881", "Complete Work", "completed"),
                ("RJ00088882", "Partial Work", "partial"),
            ):
                meta = WorkMetadata(
                    rj_id=rj, title=title, circle="TC", cv=[], tags=[],
                    price=0, source_url="", dl_count=0, rating=0.0,
                    release_date="", cover_url="",
                )
                db.register(meta, 1000, Path(temp) / rj, status=status)
            found = {row["rj_id"]: row["status"] for row in db.search("")}
            assert found["RJ00088881"] == "completed"
            assert found["RJ00088882"] == "partial"

    assert STATUS_LABELS["completed"][0] == "已完成"
    assert STATUS_LABELS["partial"][0] == "部分完成"
    assert STATUS_LABELS["missing"][0] == "文件缺失"
    print("  ✓ 数据状态和中文标签正确")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
