#!/usr/bin/env python3
"""Portable library pagination diagnostic with 129 indexed items."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    from core.database import LibraryVault

    print(f"\n{'='*60}\n  资源库分页 129 项测试\n{'='*60}\n")
    with TemporaryDirectory(prefix="arsm-library-page-") as temp:
        with LibraryVault(Path(temp) / "history.db") as db:
            for index in range(1, 130):
                rj = f"RJ{90000000 + index:08d}"
                db.execute_write(
                    """INSERT INTO library_items
                       (rj_id, folder_path, folder_name, total_files, total_size,
                        audio_count, has_audio, has_cover, warnings_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (rj, str(Path(temp) / rj), f"Test Item {index:03d}",
                     index, index * 100, 1, 1, 1, "[]"),
                )
            seen = set()
            for page in range(7):
                result = db.get_library_page(
                    search="", offset=page * 20, limit=20)
                seen.update(row["rj_id"] for row in result["items"])
            assert len(seen) == 129
            assert db.get_library_page(search="Item 129", offset=0, limit=20)["total"] == 1
    print("  ✓ 7 页覆盖 129 个索引项，搜索分页正确")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
