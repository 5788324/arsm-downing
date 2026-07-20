#!/usr/bin/env python3
"""Portable resource-library status mapping diagnostic."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    from core.database import LibraryVault
    from core.models import WorkMetadata
    from ui.views.library_view import STATUS_LABELS

    print(f"\n{'='*60}\n  资源库布局数据测试\n{'='*60}\n")
    with TemporaryDirectory(prefix="arsm-library-layout-") as temp:
        with LibraryVault(Path(temp) / "history.db") as db:
            for index, status in enumerate(("completed", "partial", "external"), 1):
                rj = f"RJ{99010000 + index:08d}"
                meta = WorkMetadata(
                    rj_id=rj, title=f"Test {status}", circle="TC",
                    cv=[], tags=[], price=0, source_url="", dl_count=0,
                    rating=0.0, release_date="", cover_url="",
                )
                db.register(meta, 100, Path(temp) / rj, status=status)

            results = db.search("")
            statuses = {row["status"] for row in results}
            assert {"completed", "partial", "external"} <= statuses
            print("  ✓ 临时数据库加载 completed/partial/external")

    for status in ("completed", "partial", "external", "verified", "missing"):
        assert status in STATUS_LABELS
        print(f"  ✓ STATUS_LABELS[{status}] = {STATUS_LABELS[status][0]}")
    print(f"\n{'='*60}\n  ✓ 资源库布局数据测试通过\n{'='*60}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
