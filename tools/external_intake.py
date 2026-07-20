"""Read-only external library intake planner.

The module deliberately separates *planning* from *execution*.  Planning may
inspect a configured directory and write a JSON/text report.  It must not move
files, mutate SQLite, start download workers, or refresh metadata.

Mutating compatibility entry points remain fail-closed until TAKEOVER-T2/T3
replace them with a transactional service.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from contextlib import closing
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

PLAN_SCHEMA_VERSION = 1
ACTION_CLASSIFICATIONS = (
    "already_normalized",
    "needs_title_layer",
    "needs_rename_top_level",
    "quarantine_candidate",
    "duplicate_review",
    "fatal",
)
AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".opus"}
RJ_RE = re.compile(r"(?:RJ)?(\d{6,8})", re.IGNORECASE)
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

EXTERNAL_INTAKE_EXECUTION_ENABLED = False
EXECUTION_STOP_MESSAGE = (
    "STOP: external intake mutations are frozen. "
    "Only scan, dry-run planning, report generation, and read-only file-list "
    "verification are allowed."
)


class ExternalIntakeExecutionDisabled(RuntimeError):
    """Raised before a legacy mutating entry point can create side effects."""


def _require_execution_enabled() -> None:
    if not EXTERNAL_INTAKE_EXECUTION_ENABLED:
        raise ExternalIntakeExecutionDisabled(EXECUTION_STOP_MESSAGE)


@dataclass(frozen=True)
class PlanNotice:
    code: str
    message: str
    source: str = ""
    rj_id: str = ""


@dataclass
class ExternalIntakeAction:
    source: str
    source_name: str
    rj_id: str
    classification: str
    reason: str
    target_root: str = ""
    target_content_dir: str = ""
    files_at_root: int = 0
    subdirectories: int = 0
    has_part: bool = False
    has_symlink: bool = False
    is_empty: bool = False
    issues: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.classification not in ACTION_CLASSIFICATIONS:
            raise ValueError(f"Unsupported classification: {self.classification}")


@dataclass
class ExternalIntakePlan:
    root: str
    root_exists: bool
    scanned_top_dirs: int = 0
    unique_rj: int = 0
    actions: list[dict[str, Any]] = field(default_factory=list)
    fatal_blockers: list[dict[str, str]] = field(default_factory=list)
    review_required: list[dict[str, str]] = field(default_factory=list)
    quarantine_actions: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)
    can_execute: bool = False
    schema_version: int = PLAN_SCHEMA_VERSION
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    quarantine_root: str = ""
    execution_frozen: bool = True
    ready_without_freeze: bool = False
    counts: dict[str, int] = field(
        default_factory=lambda: {name: 0 for name in ACTION_CLASSIFICATIONS}
    )

    def add_action(self, action: ExternalIntakeAction) -> None:
        payload = asdict(action)
        self.actions.append(payload)
        self.counts[action.classification] += 1

        if action.classification == "fatal":
            self.fatal_blockers.append(
                asdict(
                    PlanNotice(
                        code=action.reason,
                        message=_notice_message(action),
                        source=action.source,
                        rj_id=action.rj_id,
                    )
                )
            )
        elif action.classification == "duplicate_review" or action.issues:
            self.review_required.append(
                asdict(
                    PlanNotice(
                        code=action.reason,
                        message=_notice_message(action),
                        source=action.source,
                        rj_id=action.rj_id,
                    )
                )
            )

        if action.classification == "quarantine_candidate":
            self.quarantine_actions.append(payload)

    def add_fatal(self, code: str, message: str, *, source: str = "") -> None:
        self.fatal_blockers.append(asdict(PlanNotice(code, message, source=source)))

    def add_warning(self, code: str, message: str, *, source: str = "") -> None:
        self.warnings.append(asdict(PlanNotice(code, message, source=source)))

    def finalize(self) -> None:
        self.scanned_top_dirs = len(self.actions)
        self.unique_rj = len({a["rj_id"] for a in self.actions if a["rj_id"]})
        self.ready_without_freeze = not self.fatal_blockers and not self.review_required
        self.can_execute = bool(
            EXTERNAL_INTAKE_EXECUTION_ENABLED and self.ready_without_freeze
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _notice_message(action: ExternalIntakeAction) -> str:
    label = action.rj_id or action.source_name or action.source
    return f"{label}: {action.reason}"


def norm_rj(name: str) -> str:
    match = RJ_RE.search(name or "")
    return f"RJ{int(match.group(1)):08d}" if match else ""


def safe_name(value: str, maxlen: int = 80) -> str:
    """Return a Windows-safe path component without inventing a title."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", (value or "")).strip(" .")
    cleaned = cleaned[:maxlen].rstrip(" .")
    if not cleaned:
        return ""
    if cleaned.upper() in WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned


def _extract_title(name: str, rj_id: str) -> str:
    match = RJ_RE.search(name)
    if not match:
        return name.strip()
    suffix = name[match.end() :].strip(" []【】()（）-_—")
    return suffix if suffix and suffix != rj_id else ""


def _coerce_path(value: str | os.PathLike[str] | None) -> Path | None:
    if value is None:
        return None
    text = str(value).strip()
    return Path(text).expanduser() if text else None


def _resolved(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError):
        return path.absolute()


def _is_filesystem_root(path: Path) -> bool:
    resolved = _resolved(path)
    return resolved == Path(resolved.anchor) if resolved.anchor else False


def _is_within(parent: Path, child: Path) -> bool:
    try:
        _resolved(child).relative_to(_resolved(parent))
        return True
    except (ValueError, OSError, RuntimeError):
        return False


def _validate_roots(plan: ExternalIntakePlan, root: Path | None, quarantine: Path | None) -> bool:
    if root is None:
        plan.add_fatal(
            "root_not_configured",
            "External intake root is not configured. Set external_intake_root first.",
        )
        return False

    if not root.is_absolute():
        plan.add_fatal(
            "root_not_absolute",
            "External intake root must be an absolute path.",
            source=str(root),
        )
        return False

    if _is_filesystem_root(root):
        plan.add_fatal(
            "unsafe_root",
            "A drive/filesystem root cannot be used as the external intake root.",
            source=str(root),
        )
        return False

    if not root.exists():
        plan.add_fatal(
            "root_not_found",
            "Configured external intake root does not exist.",
            source=str(root),
        )
        return False

    if not root.is_dir():
        plan.add_fatal(
            "root_not_directory",
            "Configured external intake root is not a directory.",
            source=str(root),
        )
        return False

    if root.is_symlink():
        plan.add_fatal(
            "root_is_symlink",
            "External intake root may not be a symbolic link.",
            source=str(root),
        )
        return False

    if not os.access(root, os.R_OK):
        plan.add_fatal(
            "root_not_readable",
            "Configured external intake root is not readable.",
            source=str(root),
        )
        return False

    if quarantine is None:
        plan.add_warning(
            "quarantine_root_not_configured",
            "No quarantine root is configured; quarantine candidates cannot be executed later.",
        )
    else:
        if not quarantine.is_absolute():
            plan.add_fatal(
                "quarantine_root_not_absolute",
                "Quarantine root must be an absolute path.",
                source=str(quarantine),
            )
        elif _is_filesystem_root(quarantine):
            plan.add_fatal(
                "unsafe_quarantine_root",
                "A drive/filesystem root cannot be used as the quarantine root.",
                source=str(quarantine),
            )
        elif (
            _resolved(quarantine) == _resolved(root)
            or _is_within(root, quarantine)
            or _is_within(quarantine, root)
        ):
            plan.add_fatal(
                "unsafe_quarantine_root",
                "Quarantine root must be separate from and outside the active intake tree.",
                source=str(quarantine),
            )
        elif quarantine.exists() and not quarantine.is_dir():
            plan.add_fatal(
                "quarantine_root_not_directory",
                "Configured quarantine root exists but is not a directory.",
                source=str(quarantine),
            )
        elif quarantine.is_symlink():
            plan.add_fatal(
                "quarantine_root_is_symlink",
                "Quarantine root may not be a symbolic link.",
                source=str(quarantine),
            )

    return not plan.fatal_blockers


def _scan_tree_flags(directory: Path) -> tuple[bool, bool, list[str]]:
    """Return tree flags and scan errors without following linked directories."""
    has_part = False
    has_symlink = False
    scan_errors: list[str] = []

    def on_error(error: OSError) -> None:
        scan_errors.append(str(error))

    for current_root, dir_names, file_names in os.walk(
        directory, followlinks=False, onerror=on_error
    ):
        current = Path(current_root)
        safe_dirs: list[str] = []
        for name in dir_names:
            child = current / name
            if child.is_symlink():
                has_symlink = True
            else:
                safe_dirs.append(name)
        dir_names[:] = safe_dirs

        for name in file_names:
            child = current / name
            if child.is_symlink():
                has_symlink = True
            if name.casefold().endswith(".part"):
                has_part = True
    return has_part, has_symlink, scan_errors


def _inspect_directory(
    directory: Path,
) -> tuple[list[Path], list[Path], bool, bool, list[str]]:
    entries = list(directory.iterdir())
    files = [entry for entry in entries if entry.is_file() and not entry.is_symlink()]
    directories = [entry for entry in entries if entry.is_dir() and not entry.is_symlink()]
    has_part, has_symlink, scan_errors = _scan_tree_flags(directory)
    has_symlink = has_symlink or any(entry.is_symlink() for entry in entries)
    return files, directories, has_part, has_symlink, scan_errors


def _target_conflict(root: Path, source: Path, target: Path) -> str:
    if not _is_within(root, target) or _resolved(target) == _resolved(root):
        return "target_escapes_root"
    if target.exists() and _resolved(target) != _resolved(source):
        return "target_root_conflict"
    return ""


def _classify_unique_dir(root: Path, directory: Path, rj_id: str) -> ExternalIntakeAction:
    source_name = directory.name
    try:
        if directory.is_symlink():
            return ExternalIntakeAction(
                source=str(directory),
                source_name=source_name,
                rj_id=rj_id,
                classification="fatal",
                reason="source_is_symlink",
            )

        files, subdirectories, has_part, has_symlink, scan_errors = _inspect_directory(
            directory
        )
    except OSError as exc:
        return ExternalIntakeAction(
            source=str(directory),
            source_name=source_name,
            rj_id=rj_id,
            classification="fatal",
            reason="source_unreadable",
            issues=[str(exc)],
        )

    common = dict(
        source=str(directory),
        source_name=source_name,
        rj_id=rj_id,
        files_at_root=len(files),
        subdirectories=len(subdirectories),
        has_part=has_part,
        has_symlink=has_symlink,
        is_empty=not files and not subdirectories,
    )

    if scan_errors:
        return ExternalIntakeAction(
            **common,
            classification="fatal",
            reason="source_tree_unreadable",
            issues=scan_errors,
        )

    if has_symlink:
        return ExternalIntakeAction(
            **common,
            classification="fatal",
            reason="source_contains_symlink",
        )

    if has_part:
        return ExternalIntakeAction(
            **common,
            classification="quarantine_candidate",
            reason="has_part_files",
        )

    if not files and not subdirectories:
        return ExternalIntakeAction(
            **common,
            classification="quarantine_candidate",
            reason="empty_directory",
        )

    is_pure_rj = source_name.casefold() == rj_id.casefold()
    target_root = root / rj_id

    if not is_pure_rj:
        conflict = _target_conflict(root, directory, target_root)
        title = safe_name(_extract_title(source_name, rj_id))
        target_content = target_root / title if title else None

        if conflict:
            return ExternalIntakeAction(
                **common,
                classification="fatal",
                reason=conflict,
                target_root=str(target_root),
                target_content_dir=str(target_content) if target_content else "",
            )

        issues: list[str] = []
        if not title:
            issues.append("metadata_title_required")

        return ExternalIntakeAction(
            **common,
            classification="needs_rename_top_level",
            reason="top_level_name_not_canonical",
            target_root=str(target_root),
            target_content_dir=str(target_content) if target_content else "",
            issues=issues,
        )

    if files:
        issues = []
        target_content = ""
        if len(subdirectories) == 1:
            target_content = str(subdirectories[0])
            if subdirectories[0].is_file():
                return ExternalIntakeAction(
                    **common,
                    classification="fatal",
                    reason="target_content_is_file",
                    target_root=str(target_root),
                    target_content_dir=target_content,
                )
        elif not subdirectories:
            issues.append("metadata_title_required")
        else:
            issues.append("ambiguous_title_directories")

        return ExternalIntakeAction(
            **common,
            classification="needs_title_layer",
            reason="files_at_rj_root",
            target_root=str(target_root),
            target_content_dir=target_content,
            issues=issues,
        )

    issues = ["multiple_title_directories"] if len(subdirectories) > 1 else []
    return ExternalIntakeAction(
        **common,
        classification="already_normalized",
        reason="canonical_rj_root_with_title_directory",
        target_root=str(target_root),
        target_content_dir=str(subdirectories[0]) if len(subdirectories) == 1 else "",
        issues=issues,
    )


def build_external_intake_plan(
    root: str | os.PathLike[str] | None,
    quarantine_root: str | os.PathLike[str] | None = None,
) -> ExternalIntakePlan:
    """Build a complete, deterministic, read-only plan for direct child folders."""
    root_path = _coerce_path(root)
    quarantine_path = _coerce_path(quarantine_root)
    plan = ExternalIntakePlan(
        root=str(root_path) if root_path else "",
        root_exists=bool(root_path and root_path.exists()),
        quarantine_root=str(quarantine_path) if quarantine_path else "",
        execution_frozen=not EXTERNAL_INTAKE_EXECUTION_ENABLED,
    )

    if not _validate_roots(plan, root_path, quarantine_path):
        plan.finalize()
        return plan

    assert root_path is not None  # narrowed by _validate_roots

    try:
        top_entries = sorted(root_path.iterdir(), key=lambda item: item.name.casefold())
    except OSError as exc:
        plan.add_fatal("root_scan_failed", str(exc), source=str(root_path))
        plan.finalize()
        return plan

    directories: list[Path] = []
    for entry in top_entries:
        try:
            if entry.is_dir() or entry.is_symlink():
                directories.append(entry)
            else:
                plan.add_warning(
                    "top_level_file_ignored",
                    "Top-level files are ignored; only direct child directories are planned.",
                    source=str(entry),
                )
        except OSError as exc:
            plan.add_warning("top_level_entry_unreadable", str(exc), source=str(entry))

    grouped: dict[str, list[Path]] = {}
    unmatched: list[Path] = []
    for directory in directories:
        if directory.is_symlink():
            plan.add_action(
                ExternalIntakeAction(
                    source=str(directory),
                    source_name=directory.name,
                    rj_id=norm_rj(directory.name),
                    classification="fatal",
                    reason="source_is_symlink",
                    has_symlink=True,
                )
            )
            continue
        rj_id = norm_rj(directory.name)
        if rj_id:
            grouped.setdefault(rj_id, []).append(directory)
        else:
            unmatched.append(directory)

    for directory in unmatched:
        plan.add_action(
            ExternalIntakeAction(
                source=str(directory),
                source_name=directory.name,
                rj_id="",
                classification="quarantine_candidate",
                reason="no_rj_match",
            )
        )

    for rj_id in sorted(grouped):
        candidates = grouped[rj_id]
        if len(candidates) > 1:
            sources = ", ".join(candidate.name for candidate in candidates)
            for candidate in candidates:
                plan.add_action(
                    ExternalIntakeAction(
                        source=str(candidate),
                        source_name=candidate.name,
                        rj_id=rj_id,
                        classification="duplicate_review",
                        reason="duplicate_rj",
                        target_root=str(root_path / rj_id),
                        issues=[f"duplicates={sources}"],
                    )
                )
            continue

        plan.add_action(_classify_unique_dir(root_path, candidates[0], rj_id))

    if plan.quarantine_actions and quarantine_path is None:
        plan.add_fatal(
            "quarantine_root_required",
            "The plan contains quarantine candidates but no quarantine root is configured.",
        )

    plan.finalize()
    return plan


def scan_structure(
    root: str | os.PathLike[str] | None = None,
    quarantine_root: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """UI-compatible fixed-schema scan result."""
    return build_external_intake_plan(root, quarantine_root).to_dict()


def scan_top_dirs(
    root: str | os.PathLike[str] | None = None,
    quarantine_root: str | os.PathLike[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Compatibility wrapper returning ``(actions, plan)``."""
    payload = scan_structure(root, quarantine_root)
    return payload["actions"], payload


def write_plan_report(
    plan: ExternalIntakePlan | Mapping[str, Any],
    report_root: str | os.PathLike[str] = ".local_backups",
) -> Path:
    """Write the complete plan atomically and return the report directory."""
    payload = plan.to_dict() if isinstance(plan, ExternalIntakePlan) else dict(plan)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    report_dir = Path(report_root) / f"external_intake_{timestamp}"
    report_dir.mkdir(parents=True, exist_ok=False)

    json_target = report_dir / "external_intake_plan.json"
    json_temp = report_dir / ".external_intake_plan.json.tmp"
    json_temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    json_temp.replace(json_target)

    counts = payload.get("counts", {})
    summary_lines = [
        f"schema_version: {payload.get('schema_version')}",
        f"generated_at: {payload.get('generated_at')}",
        f"root: {payload.get('root')}",
        f"root_exists: {payload.get('root_exists')}",
        f"scanned_top_dirs: {payload.get('scanned_top_dirs')}",
        f"unique_rj: {payload.get('unique_rj')}",
        f"fatal_blockers: {len(payload.get('fatal_blockers', []))}",
        f"review_required: {len(payload.get('review_required', []))}",
        f"quarantine_actions: {len(payload.get('quarantine_actions', []))}",
        f"warnings: {len(payload.get('warnings', []))}",
        f"execution_frozen: {payload.get('execution_frozen')}",
        f"can_execute: {payload.get('can_execute')}",
    ]
    summary_lines.extend(f"count.{name}: {counts.get(name, 0)}" for name in ACTION_CLASSIFICATIONS)
    (report_dir / "external_intake_summary.txt").write_text(
        "\n".join(summary_lines) + "\n", encoding="utf-8"
    )
    return report_dir


def _extract_track_names(tracks: Any) -> list[str]:
    """Recursively extract leaf file names from metadata track JSON."""
    names: list[str] = []
    if isinstance(tracks, list):
        for track in tracks:
            if not isinstance(track, dict):
                continue
            children = track.get("children")
            if isinstance(children, list):
                names.extend(_extract_track_names(children))
            elif isinstance(track.get("title"), str):
                names.append(track["title"])
    return names


def verify_filelist(rj_id: str, disk_dir: Path, db_conn: sqlite3.Connection) -> dict[str, Any]:
    """Compare cached metadata tracks with disk files using a read-only connection."""
    result: dict[str, Any] = {
        "rj_id": rj_id,
        "total_tracks": 0,
        "matched": 0,
        "missing_audio": [],
        "missing_other": 0,
        "has_part": False,
        "empty_dir": False,
        "verdict": "ok",
    }

    cached = db_conn.execute(
        "SELECT tracks_json FROM metadata_cache WHERE rj_id=?", (rj_id,)
    ).fetchone()
    if not cached or not cached[0]:
        result["verdict"] = "no_metadata"
        return result

    try:
        tracks = json.loads(cached[0])
    except (TypeError, json.JSONDecodeError):
        result["verdict"] = "bad_metadata"
        return result

    disk_files: dict[str, Path] = {}
    try:
        iterator: Iterable[Path] = disk_dir.rglob("*") if disk_dir.exists() else []
        for file_path in iterator:
            if file_path.is_file():
                disk_files[file_path.name.casefold()] = file_path
    except OSError:
        result["verdict"] = "disk_unreadable"
        return result

    if any(name.endswith(".part") for name in disk_files):
        result["has_part"] = True
        result["verdict"] = "has_part"
        return result

    if not disk_files:
        result["empty_dir"] = True
        result["verdict"] = "empty"
        return result

    track_names = _extract_track_names(tracks)
    result["total_tracks"] = len(track_names)
    disk_stems = {Path(name).stem.casefold() for name in disk_files}

    for track_name in track_names:
        track_stem = Path(track_name).stem.casefold()
        if track_stem in disk_stems:
            result["matched"] += 1
            continue

        if Path(track_name).suffix.casefold() in AUDIO_EXTENSIONS:
            result["missing_audio"].append(track_name)
        else:
            result["missing_other"] += 1

    if result["missing_audio"]:
        result["verdict"] = "missing_audio_files"
    elif result["total_tracks"] and result["matched"] < result["total_tracks"] * 0.5:
        result["verdict"] = "severely_mismatched"

    return result


async def refresh_metadata(rj_ids: Sequence[str], config: Any) -> dict[str, Any]:
    """Compatibility entry point; metadata refresh remains frozen."""
    del rj_ids, config
    _require_execution_enabled()
    raise ExternalIntakeExecutionDisabled(EXECUTION_STOP_MESSAGE)


def execute_normalize(
    dirs_info: Sequence[Mapping[str, Any]], db_path: str | os.PathLike[str] = "history.db"
) -> None:
    """Compatibility entry point; legacy mutating implementation was removed."""
    del dirs_info, db_path
    _require_execution_enabled()
    raise ExternalIntakeExecutionDisabled(EXECUTION_STOP_MESSAGE)


def _open_read_only_database(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    connection = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _verify_planned_filelists(
    actions: Sequence[Mapping[str, Any]], db_path: Path
) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    with closing(_open_read_only_database(db_path)) as connection:
        for action in actions:
            if action.get("classification") in {"fatal", "duplicate_review", "quarantine_candidate"}:
                continue
            rj_id = str(action.get("rj_id") or "")
            source = Path(str(action.get("source") or ""))
            if not rj_id or not source.exists():
                continue
            result = verify_filelist(rj_id, source, connection)
            if result["verdict"] != "ok":
                mismatches.append(result)
    return mismatches


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Build a read-only plan (default).")
    parser.add_argument("--root", help="Absolute external intake root.")
    parser.add_argument("--quarantine-root", help="Absolute quarantine root outside intake root.")
    parser.add_argument("--report-root", default=".local_backups")
    parser.add_argument("--db-path", default="history.db")
    parser.add_argument("--verify-filelist", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-bulk", action="store_true")
    parser.add_argument("--refresh-metadata", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    del args.confirm_bulk

    if args.execute or args.refresh_metadata:
        print(EXECUTION_STOP_MESSAGE, file=sys.stderr)
        return 2

    root = args.root or os.environ.get("ARSM_EXTERNAL_INTAKE_ROOT")
    quarantine_root = args.quarantine_root or os.environ.get("ARSM_EXTERNAL_QUARANTINE_ROOT")
    plan = build_external_intake_plan(root, quarantine_root)
    payload = plan.to_dict()

    print(
        f"Scanned: {payload['scanned_top_dirs']} dirs, "
        f"{payload['unique_rj']} unique RJ"
    )
    for classification in ACTION_CLASSIFICATIONS:
        print(f"  {classification}: {payload['counts'][classification]}")
    print(f"  fatal_blockers: {len(payload['fatal_blockers'])}")
    print(f"  review_required: {len(payload['review_required'])}")
    print(f"  warnings: {len(payload['warnings'])}")

    report_dir = write_plan_report(plan, args.report_root)
    print(f"Report: {report_dir}")

    if args.verify_filelist:
        try:
            mismatches = _verify_planned_filelists(payload["actions"], Path(args.db_path))
        except FileNotFoundError:
            print(
                f"BLOCKED: {args.db_path} does not exist; read-only verification cannot run.",
                file=sys.stderr,
            )
            return 2
        print(f"File-list verify: {len(mismatches)} mismatches")
        for mismatch in mismatches[:10]:
            print(
                f"  {mismatch['rj_id']}: {mismatch['verdict']} "
                f"(missing_audio={len(mismatch['missing_audio'])})"
            )

    return 2 if payload["fatal_blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
