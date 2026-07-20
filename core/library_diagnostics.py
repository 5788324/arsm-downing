"""Pure helpers for resource-library diagnostics and presentation.

The UI previously embedded user-specific drive letters, fake RJ identifiers,
and direct filesystem/SQLite access.  This module keeps classification rules
portable and testable so the Flet view only renders a prepared snapshot.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Callable, Iterable, Mapping, Sequence

CANONICAL_RJ_RE = re.compile(r"^RJ\d{8}$", re.IGNORECASE)

ANOMALY_ORDER = (
    "indexed_path_missing",
    "configured_root_not_indexed",
    "outside_configured_roots",
    "empty_directory",
    "no_images",
    "path_mismatch",
    "noncanonical_rj",
)

ANOMALY_LABELS = {
    "indexed_path_missing": "路径丢失",
    "configured_root_not_indexed": "目录未索引",
    "outside_configured_roots": "配置目录之外",
    "empty_directory": "空目录",
    "no_images": "无图片",
    "path_mismatch": "路径不匹配",
    "noncanonical_rj": "非标准 RJ",
}


@dataclass(frozen=True)
class LibraryAnomaly:
    rj_id: str
    title: str
    works_status: str
    local_path: str
    indexed: bool
    total_files: int
    total_size: int
    warnings: tuple[str, ...]
    category: str

    def to_dict(self) -> dict:
        return {
            "rj_id": self.rj_id,
            "title": self.title,
            "works_status": self.works_status,
            "local_path": self.local_path,
            "indexed": self.indexed,
            "total_files": self.total_files,
            "total_size": self.total_size,
            "warnings": list(self.warnings),
            "category": self.category,
        }


def normalize_path_key(value: str | Path | None) -> str:
    """Normalize Windows/POSIX paths without requiring the host OS to match."""
    if value is None:
        return ""
    text = str(value).strip().replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    if len(text) > 1:
        text = text.rstrip("/")
    return text.casefold()


def path_is_under_roots(path: str | Path | None,
                        roots: Iterable[str | Path]) -> bool:
    candidate = normalize_path_key(path)
    if not candidate:
        return False
    for root in roots:
        base = normalize_path_key(root)
        if base and (candidate == base or candidate.startswith(base + "/")):
            return True
    return False


def parse_warnings(raw: object) -> tuple[str, ...]:
    if isinstance(raw, (list, tuple)):
        return tuple(str(item) for item in raw)
    if not raw:
        return ()
    try:
        value = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return (str(raw),)
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    return (str(value),)


def _matches_search(item: Mapping[str, object], search: str) -> bool:
    query = search.strip().casefold()
    if not query:
        return True
    haystack = " ".join(
        str(item.get(key, ""))
        for key in ("rj_id", "title", "local_path", "category")
    ).casefold()
    return query in haystack


def classify_library_anomalies(
    works_rows: Sequence[Mapping[str, object]],
    library_rows: Sequence[Mapping[str, object]],
    *,
    configured_roots: Iterable[str | Path],
    path_exists: Callable[[str], bool] | None = None,
    search: str = "",
) -> dict[str, list[dict]]:
    """Classify library inconsistencies without user-specific path rules."""
    exists = path_exists or (lambda value: Path(value).exists())
    roots = tuple(configured_roots)
    library_by_rj = {
        str(row.get("rj_id", "")).upper(): row for row in library_rows
    }
    groups: dict[str, list[dict]] = {key: [] for key in ANOMALY_ORDER}

    for work in works_rows:
        rj_id = str(work.get("rj_id", "")).upper()
        local_path = str(work.get("local_path") or "")
        indexed = library_by_rj.get(rj_id)
        warnings = parse_warnings(indexed.get("warnings_json") if indexed else None)

        categories: list[str] = []
        if not CANONICAL_RJ_RE.fullmatch(rj_id):
            categories.append("noncanonical_rj")
        try:
            local_exists = bool(local_path) and exists(local_path)
        except OSError:
            local_exists = False
        if local_path and not local_exists:
            categories.append("indexed_path_missing")
        elif local_path and path_is_under_roots(local_path, roots) and not indexed:
            categories.append("configured_root_not_indexed")
        elif local_path and roots and not path_is_under_roots(local_path, roots):
            categories.append("outside_configured_roots")
        if "empty_directory" in warnings:
            categories.append("empty_directory")
        if "no_images" in warnings:
            categories.append("no_images")
        if "path_mismatch_with_works_local_path" in warnings:
            categories.append("path_mismatch")

        for category in dict.fromkeys(categories):
            anomaly = LibraryAnomaly(
                rj_id=rj_id,
                title=str(work.get("title") or "")[:80],
                works_status=str(work.get("status") or ""),
                local_path=local_path,
                indexed=indexed is not None,
                total_files=int((indexed or {}).get("total_files") or 0),
                total_size=int((indexed or {}).get("total_size") or 0),
                warnings=warnings,
                category=category,
            ).to_dict()
            if _matches_search(anomaly, search):
                groups[category].append(anomaly)

    for values in groups.values():
        values.sort(key=lambda item: (item["rj_id"], item["local_path"]))
    return groups


def flatten_anomaly_groups(groups: Mapping[str, Sequence[dict]],
                           selected_filter: str) -> list[dict]:
    if selected_filter == "__all__":
        result: list[dict] = []
        for key in ANOMALY_ORDER:
            result.extend(groups.get(key, ()))
        return result
    return list(groups.get(selected_filter, ()))
