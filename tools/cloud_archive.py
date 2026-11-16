"""Maintain the user-confirmed cloud archive ledger without moving media."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.database import LibraryVault


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="登记已由用户确认上传的专辑；不会上传或删除任何媒体文件。"
    )
    parser.add_argument("--db", help="history.db 路径；省略时使用 ARSM 正式配置路径")
    sub = parser.add_subparsers(dest="command", required=True)

    mark = sub.add_parser("mark", help="登记一个或多个已上传 RJ 号")
    mark.add_argument("rj_ids", nargs="+")
    mark.add_argument("--provider", default="", help="网盘名称（可选）")
    mark.add_argument("--remote-path", default="", help="网盘目录或分享位置（可选）")
    mark.add_argument("--note", default="", help="备注（可选）")
    mark.add_argument("--csv", help="CSV 备份路径；默认与数据库同目录")

    listing = sub.add_parser("list", help="列出归档记录")
    listing.add_argument("--json", action="store_true", help="输出 JSON")

    export = sub.add_parser("export", help="重新导出 CSV 备份")
    export.add_argument("destination", nargs="?", help="CSV 路径；默认与数据库同目录")
    return parser


def _csv_path(vault: LibraryVault, value: str | None) -> Path:
    if value:
        return Path(value).expanduser()
    return Path(vault.db_path).with_name("cloud_archives.csv")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    vault = LibraryVault(args.db) if args.db else LibraryVault()
    try:
        if args.command == "mark":
            records = vault.mark_cloud_archives(
                args.rj_ids,
                provider=args.provider,
                remote_path=args.remote_path,
                note=args.note,
            )
            csv_path = vault.export_cloud_archives_csv(_csv_path(vault, args.csv))
            print(f"已登记 {len(records)} 项；未移动或删除媒体文件。")
            for record in records:
                print(f"  {record['rj_id']}  {record['title']}")
            print(f"CSV 备份：{csv_path}")
            return 0
        if args.command == "list":
            records = vault.list_cloud_archives()
            if args.json:
                print(json.dumps(records, ensure_ascii=False, indent=2, default=str))
            else:
                print(f"云端归档：{len(records)} 项")
                for record in records:
                    location = record.get("remote_path") or record.get("provider") or "未填写位置"
                    print(f"  {record['rj_id']}  {record.get('title', '')}  [{location}]")
            return 0
        csv_path = vault.export_cloud_archives_csv(_csv_path(vault, args.destination))
        print(f"CSV 备份：{csv_path}")
        return 0
    except ValueError as exc:
        print(f"未登记：{exc}", file=sys.stderr)
        return 2
    finally:
        vault.close()


if __name__ == "__main__":
    raise SystemExit(main())
