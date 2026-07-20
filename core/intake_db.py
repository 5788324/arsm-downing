"""Transactional database helpers for external-intake path changes.

This module contains no filesystem mutations.  It captures auditable database
preimages/postimages and updates only rows whose stored path matches the
explicit source path.  A duplicate RJ at another path is therefore never
modified merely because it shares the same RJ id.
"""
from __future__ import annotations

import hashlib
import json
import ntpath
import posixpath
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping

SNAPSHOT_SCHEMA_VERSION = 1
PENDING_DOWNLOAD_STATUSES = {
    "queued",
    "paused",
    "downloading",
    "failed",
    "resuming",
}


@dataclass(frozen=True)
class IntakePathUpdateRequest:
    """One database-only path update requested by a higher-level service."""

    rj_id: str
    source_path: str
    target_path: str
    expected_preimage_token: str = ""
    ensure_library_index: bool = True


@dataclass
class IntakePathUpdateResult:
    """Serializable outcome of a database path transaction."""

    success: bool
    rj_id: str
    source_path: str
    target_path: str
    updated_rows: dict[str, int] = field(default_factory=dict)
    preimage: dict[str, Any] = field(default_factory=dict)
    postimage: dict[str, Any] = field(default_factory=dict)
    preimage_token: str = ""
    postimage_token: str = ""
    error_code: str = ""
    error: str = ""
    transaction_id: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime(
            "%Y%m%dT%H%M%S.%fZ"
        )
    )

    @property
    def updated(self) -> int:
        return sum(self.updated_rows.values())

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["updated"] = self.updated
        return payload


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        is not None
    )


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _load_json(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _canonical_snapshot(snapshot: Mapping[str, Any]) -> bytes:
    """Serialize stable business fields only; omit volatile capture time/token."""
    stable = {
        key: value
        for key, value in snapshot.items()
        if key not in {"captured_at", "snapshot_token"}
    }
    return json.dumps(
        stable,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def snapshot_token(snapshot: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_snapshot(snapshot)).hexdigest()


def capture_external_intake_snapshot(
    conn: sqlite3.Connection, rj_id: str
) -> dict[str, Any]:
    """Capture all DB records relevant to one external-intake RJ.

    Missing legacy/new tables are represented as empty collections so this
    query remains usable against older databases in read-only mode.
    """
    work = None
    metadata = None
    library_items: list[dict[str, Any]] = []
    library_index: list[dict[str, Any]] = []
    downloads: list[dict[str, Any]] = []

    if _table_exists(conn, "works"):
        work = _row_to_dict(
            conn.execute("SELECT * FROM works WHERE rj_id=?", (rj_id,)).fetchone()
        )

    if _table_exists(conn, "metadata_cache"):
        row = conn.execute(
            """SELECT rj_id, title, circle, cover_url, metadata_json,
                      tracks_json, fetched_at, updated_at
               FROM metadata_cache WHERE rj_id=?""",
            (rj_id,),
        ).fetchone()
        if row is not None:
            metadata = dict(row)
            metadata["metadata"] = _load_json(metadata.pop("metadata_json", None), {})
            metadata["tracks"] = _load_json(metadata.pop("tracks_json", None), [])

    if _table_exists(conn, "library_items"):
        library_items = _rows_to_dicts(
            conn.execute(
                "SELECT * FROM library_items WHERE rj_id=? ORDER BY folder_path",
                (rj_id,),
            ).fetchall()
        )

    if _table_exists(conn, "library_index"):
        library_index = _rows_to_dicts(
            conn.execute(
                "SELECT * FROM library_index WHERE rj_id=? ORDER BY work_dir",
                (rj_id,),
            ).fetchall()
        )

    if _table_exists(conn, "downloads"):
        downloads = _rows_to_dicts(
            conn.execute(
                "SELECT * FROM downloads WHERE rj_id=? ORDER BY id", (rj_id,)
            ).fetchall()
        )

    snapshot: dict[str, Any] = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rj_id": rj_id,
        "work": work,
        "metadata": metadata,
        "library_items": library_items,
        "library_index": library_index,
        "downloads": downloads,
        "pending_downloads": sum(
            1
            for row in downloads
            if str(row.get("status") or "").casefold() in PENDING_DOWNLOAD_STATUSES
        ),
    }
    snapshot["snapshot_token"] = snapshot_token(snapshot)
    return snapshot


def _is_windows_path(value: str) -> bool:
    drive, _ = ntpath.splitdrive(value)
    return bool(drive) or "\\" in value


def _path_key(value: str) -> str:
    if _is_windows_path(value):
        return ntpath.normcase(ntpath.normpath(value))
    return posixpath.normpath(value)


def paths_equivalent(left: str, right: str) -> bool:
    return bool(left and right) and _path_key(left) == _path_key(right)


def replace_path_prefix(value: str, source: str, target: str) -> str | None:
    """Map value from source tree to target tree without substring replacement."""
    if not value:
        return None
    path_cls = PureWindowsPath if _is_windows_path(source) or _is_windows_path(value) else PurePosixPath
    source_path = path_cls(source)
    value_path = path_cls(value)
    try:
        relative = value_path.relative_to(source_path)
    except ValueError:
        return None

    target_cls = PureWindowsPath if _is_windows_path(target) else PurePosixPath
    return str(target_cls(target).joinpath(*relative.parts))


def _target_owned_by_other_rj(
    conn: sqlite3.Connection, rj_id: str, target_path: str
) -> tuple[str, str] | None:
    checks = (
        ("works", "local_path"),
        ("library_items", "folder_path"),
        ("library_index", "work_dir"),
    )
    for table, column in checks:
        if not _table_exists(conn, table):
            continue
        rows = conn.execute(
            f"SELECT rj_id, {column} AS path FROM {table} WHERE rj_id != ?",
            (rj_id,),
        ).fetchall()
        for row in rows:
            if paths_equivalent(str(row["path"] or ""), target_path):
                return table, str(row["rj_id"])
    return None


def validate_path_update(
    conn: sqlite3.Connection,
    request: IntakePathUpdateRequest,
    preimage: Mapping[str, Any],
) -> tuple[str, str]:
    """Return (error_code, message), or empty strings when valid."""
    if not request.rj_id.strip():
        return "invalid_rj_id", "rj_id is required"
    if not request.source_path.strip() or not request.target_path.strip():
        return "invalid_path", "source_path and target_path are required"
    if paths_equivalent(request.source_path, request.target_path):
        return "same_path", "source_path and target_path resolve to the same path"

    if request.expected_preimage_token and request.expected_preimage_token != preimage.get(
        "snapshot_token"
    ):
        return "preimage_changed", "database state changed after the plan was created"

    pending = int(preimage.get("pending_downloads") or 0)
    if pending:
        return (
            "pending_downloads",
            f"{request.rj_id} has {pending} pending downloads; path update refused",
        )

    work = preimage.get("work")
    if work and not paths_equivalent(str(work.get("local_path") or ""), request.source_path):
        return (
            "primary_record_protected",
            "works.local_path points to another copy; duplicate source must not replace the primary record",
        )

    item_paths = [str(row.get("folder_path") or "") for row in preimage.get("library_items", [])]
    for item_path in item_paths:
        if item_path and not (
            paths_equivalent(item_path, request.source_path)
            or paths_equivalent(item_path, request.target_path)
        ):
            return (
                "library_item_path_mismatch",
                "library_items points to a third path; reconcile the canonical item before moving",
            )

    source_index_rows = [
        row
        for row in preimage.get("library_index", [])
        if paths_equivalent(str(row.get("work_dir") or ""), request.source_path)
    ]
    target_index_rows = [
        row
        for row in preimage.get("library_index", [])
        if paths_equivalent(str(row.get("work_dir") or ""), request.target_path)
    ]
    if source_index_rows and target_index_rows:
        return (
            "target_reference_conflict",
            "library_index already contains both source and target paths for this RJ",
        )

    conflict = _target_owned_by_other_rj(conn, request.rj_id, request.target_path)
    if conflict:
        table, owner_rj = conflict
        return (
            "target_owned_by_other_rj",
            f"target path is already referenced by {owner_rj} in {table}",
        )

    matching_refs = 0
    if work and paths_equivalent(str(work.get("local_path") or ""), request.source_path):
        matching_refs += 1
    matching_refs += sum(
        1
        for row in preimage.get("library_items", [])
        if paths_equivalent(str(row.get("folder_path") or ""), request.source_path)
    )
    matching_refs += sum(
        1
        for row in preimage.get("library_index", [])
        if paths_equivalent(str(row.get("work_dir") or ""), request.source_path)
    )
    matching_refs += sum(
        1
        for row in preimage.get("downloads", [])
        if replace_path_prefix(
            str(row.get("local_path") or ""), request.source_path, request.target_path
        )
        is not None
    )
    if matching_refs == 0:
        return "no_matching_references", "no database path references match source_path"

    return "", ""


def apply_path_update(
    conn: sqlite3.Connection,
    request: IntakePathUpdateRequest,
    preimage: Mapping[str, Any] | None = None,
) -> IntakePathUpdateResult:
    """Apply one already-validated DB path update inside the caller's transaction."""
    preimage = dict(preimage or capture_external_intake_snapshot(conn, request.rj_id))
    result = IntakePathUpdateResult(
        success=False,
        rj_id=request.rj_id,
        source_path=request.source_path,
        target_path=request.target_path,
        preimage=preimage,
        preimage_token=str(preimage["snapshot_token"]),
        updated_rows={
            "works": 0,
            "downloads": 0,
            "library_items": 0,
            "library_index": 0,
        },
    )

    error_code, message = validate_path_update(conn, request, preimage)
    if error_code:
        result.error_code = error_code
        result.error = message
        return result

    work = preimage.get("work")
    if work and paths_equivalent(str(work.get("local_path") or ""), request.source_path):
        cursor = conn.execute(
            "UPDATE works SET local_path=? WHERE rj_id=?",
            (request.target_path, request.rj_id),
        )
        result.updated_rows["works"] += cursor.rowcount

    for row in preimage.get("downloads", []):
        mapped = replace_path_prefix(
            str(row.get("local_path") or ""), request.source_path, request.target_path
        )
        if mapped is None:
            continue
        cursor = conn.execute(
            "UPDATE downloads SET local_path=? WHERE id=? AND rj_id=?",
            (mapped, row["id"], request.rj_id),
        )
        result.updated_rows["downloads"] += cursor.rowcount

    for row in preimage.get("library_items", []):
        if not paths_equivalent(str(row.get("folder_path") or ""), request.source_path):
            continue
        cursor = conn.execute(
            """UPDATE library_items
               SET folder_path=?, folder_name=?
               WHERE rj_id=? AND folder_path=?""",
            (
                request.target_path,
                PureWindowsPath(request.target_path).name
                if _is_windows_path(request.target_path)
                else PurePosixPath(request.target_path).name,
                request.rj_id,
                row["folder_path"],
            ),
        )
        result.updated_rows["library_items"] += cursor.rowcount

    target_parent = (
        str(PureWindowsPath(request.target_path).parent)
        if _is_windows_path(request.target_path)
        else str(PurePosixPath(request.target_path).parent)
    )
    source_index_rows = []
    target_index_exists = False
    for row in preimage.get("library_index", []):
        row_path = str(row.get("work_dir") or "")
        if paths_equivalent(row_path, request.target_path):
            target_index_exists = True
        if not paths_equivalent(row_path, request.source_path):
            continue
        source_index_rows.append(row)
        cursor = conn.execute(
            """UPDATE library_index
               SET work_dir=?, library_path=?
               WHERE id=? AND rj_id=?""",
            (request.target_path, target_parent, row["id"], request.rj_id),
        )
        result.updated_rows["library_index"] += cursor.rowcount

    if (
        request.ensure_library_index
        and result.updated_rows["works"] > 0
        and not source_index_rows
        and not target_index_exists
        and _table_exists(conn, "library_index")
    ):
        cursor = conn.execute(
            """INSERT INTO library_index
               (rj_id, library_path, work_dir, status, size_bytes, file_count, scanned_at)
               VALUES (?, ?, ?, 'found', 0, 0, ?)""",
            (
                request.rj_id,
                target_parent,
                request.target_path,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        result.updated_rows["library_index"] += cursor.rowcount

    postimage = capture_external_intake_snapshot(conn, request.rj_id)
    result.postimage = postimage
    result.postimage_token = str(postimage["snapshot_token"])
    result.success = result.updated > 0
    if not result.success:
        result.error_code = "no_rows_updated"
        result.error = "validated transaction did not update any rows"
    return result
