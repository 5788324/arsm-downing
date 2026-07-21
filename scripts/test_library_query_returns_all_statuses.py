#!/usr/bin/env python3
"""Portable works query diagnostic covering legacy status values."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    from core.database import LibraryVault
    from core.models import WorkMetadata

    statuses = [
        "completed", "partial", "external", "verified",
        "missing", "indexed", "metadata_failed", "prepared",
    ]
    with TemporaryDirectory(prefix="arsm-library-query-") as temp:
        with LibraryVault(Path(temp) / "history.db") as db:
            for index, status in enumerate(statuses):
                rj = f"RJ{99000000 + index:08d}"
                meta = WorkMetadata(
                    rj_id=rj, title=f"Status {status}", circle="Test",
                    cv=[], tags=[], price=0, source_url="", dl_count=0,
                    rating=0.0, release_date="", cover_url="",
                )
                db.register(meta, 100, Path(temp) / rj, status=status)
            found = {row["status"] for row in db.search("", limit=0)}
            assert set(statuses) <= found
            counts = db.count_library_by_status()
            for status in statuses:
                assert counts.get(status, 0) == 1
    print("✓ 资源库查询返回全部历史状态")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
