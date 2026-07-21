"""Deterministic manifests and file mappings for external-intake plans."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

HASH_FULL_LIMIT = 8 * 1024 * 1024
HASH_SAMPLE_BYTES = 1024 * 1024
CRITICAL_SUFFIXES = {
    ".json",
    ".txt",
    ".lrc",
    ".cue",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
}
CRITICAL_NAMES = {
    "cover.jpg",
    "cover.jpeg",
    "cover.png",
    "metadata.json",
    "work.json",
}


@dataclass(frozen=True)
class PlannedFile:
    relative_path: str
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class VerifiedFile:
    relative_path: str
    size: int
    digest: str = ""
    digest_mode: str = ""


@dataclass(frozen=True)
class SourcePlanManifest:
    files: tuple[PlannedFile, ...]
    file_count: int
    total_size: int
    token: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "files": [asdict(item) for item in self.files],
            "file_count": self.file_count,
            "total_size": self.total_size,
            "token": self.token,
        }


@dataclass(frozen=True)
class VerificationManifest:
    files: tuple[VerifiedFile, ...]
    file_count: int
    total_size: int
    token: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "files": [asdict(item) for item in self.files],
            "file_count": self.file_count,
            "total_size": self.total_size,
            "token": self.token,
        }


def safe_relative(path: Path, root: Path) -> str:
    relative = path.relative_to(root)
    value = PurePosixPath(*relative.parts).as_posix()
    if not value or value == "." or value.startswith("../"):
        raise ValueError(f"unsafe relative path: {path}")
    return value


def iter_regular_files(root: str | os.PathLike[str]) -> list[Path]:
    root_path = Path(root)
    if root_path.is_symlink():
        raise ValueError(f"symbolic-link root is not allowed: {root_path}")

    files: list[Path] = []
    for current_root, dir_names, file_names in os.walk(
        root_path, followlinks=False
    ):
        current = Path(current_root)
        safe_dirs: list[str] = []
        for name in dir_names:
            child = current / name
            if child.is_symlink():
                raise ValueError(f"symbolic link is not allowed: {child}")
            safe_dirs.append(name)
        dir_names[:] = safe_dirs

        for name in file_names:
            child = current / name
            if child.is_symlink():
                raise ValueError(f"symbolic link is not allowed: {child}")
            if not child.is_file():
                raise ValueError(f"non-regular file is not allowed: {child}")
            files.append(child)

    return sorted(
        files,
        key=lambda item: safe_relative(item, root_path).casefold(),
    )


def _manifest_token(records: Iterable[Mapping[str, Any]]) -> str:
    payload = json.dumps(
        list(records),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_source_plan_manifest(
    root: str | os.PathLike[str],
) -> SourcePlanManifest:
    """Capture path, size and mtime for plan-drift detection."""
    root_path = Path(root)
    files: list[PlannedFile] = []
    total_size = 0
    for path in iter_regular_files(root_path):
        stat = path.stat()
        item = PlannedFile(
            safe_relative(path, root_path),
            int(stat.st_size),
            int(stat.st_mtime_ns),
        )
        files.append(item)
        total_size += item.size

    records = [asdict(item) for item in files]
    return SourcePlanManifest(
        tuple(files),
        len(files),
        total_size,
        _manifest_token(records),
    )


def _hash_file(path: Path) -> tuple[str, str]:
    size = path.stat().st_size
    digest = hashlib.sha256()
    if size <= HASH_FULL_LIMIT:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest(), "sha256"

    with path.open("rb") as handle:
        digest.update(handle.read(HASH_SAMPLE_BYTES))
        handle.seek(max(0, size - HASH_SAMPLE_BYTES))
        digest.update(handle.read(HASH_SAMPLE_BYTES))
    digest.update(str(size).encode("ascii"))
    return digest.hexdigest(), "sample-sha256"


def _critical_relative_paths(files: list[Path], root: Path) -> set[str]:
    if not files:
        return set()
    relatives = [safe_relative(path, root) for path in files]
    selected = {relatives[0], relatives[-1]}
    for path, relative in zip(files, relatives):
        if (
            path.name.casefold() in CRITICAL_NAMES
            or path.suffix.casefold() in CRITICAL_SUFFIXES
        ):
            selected.add(relative)
    return selected


def build_verification_manifest(
    root: str | os.PathLike[str],
) -> VerificationManifest:
    """Capture paths and sizes, plus hashes for deterministic critical files."""
    root_path = Path(root)
    paths = iter_regular_files(root_path)
    critical = _critical_relative_paths(paths, root_path)
    files: list[VerifiedFile] = []
    total_size = 0
    for path in paths:
        stat = path.stat()
        relative = safe_relative(path, root_path)
        digest = ""
        digest_mode = ""
        if relative in critical:
            digest, digest_mode = _hash_file(path)
        files.append(
            VerifiedFile(relative, int(stat.st_size), digest, digest_mode)
        )
        total_size += int(stat.st_size)

    records = [asdict(item) for item in files]
    return VerificationManifest(
        tuple(files),
        len(files),
        total_size,
        _manifest_token(records),
    )


def compare_verification_manifests(
    expected: VerificationManifest,
    actual: VerificationManifest,
) -> tuple[bool, str]:
    if expected.file_count != actual.file_count:
        return (
            False,
            f"file_count mismatch: {expected.file_count} != {actual.file_count}",
        )
    if expected.total_size != actual.total_size:
        return (
            False,
            f"total_size mismatch: {expected.total_size} != {actual.total_size}",
        )

    expected_map = {item.relative_path: item for item in expected.files}
    actual_map = {item.relative_path: item for item in actual.files}
    if expected_map.keys() != actual_map.keys():
        missing = sorted(expected_map.keys() - actual_map.keys())
        extra = sorted(actual_map.keys() - expected_map.keys())
        return (
            False,
            f"relative path mismatch: missing={missing[:5]} extra={extra[:5]}",
        )

    for relative, expected_item in expected_map.items():
        actual_item = actual_map[relative]
        if expected_item.size != actual_item.size:
            return False, f"size mismatch: {relative}"
        if expected_item.digest and expected_item.digest != actual_item.digest:
            return False, f"hash mismatch: {relative}"
    return True, ""


def _validate_relative_mapping(value: str) -> str:
    path = PurePosixPath(str(value or ""))
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"unsafe mapped relative path: {value}")
    return path.as_posix()


def build_identity_file_mappings(
    root: str | os.PathLike[str],
    *,
    prefix: str = "",
    manifest: SourcePlanManifest | None = None,
) -> list[dict[str, Any]]:
    """Return complete mappings, reusing a manifest when already available."""
    normalized_prefix = ""
    if prefix:
        normalized_prefix = _validate_relative_mapping(
            PurePosixPath(prefix).as_posix()
        )

    source_manifest = manifest or build_source_plan_manifest(root)
    mappings: list[dict[str, Any]] = []
    for item in source_manifest.files:
        target_relative = (
            PurePosixPath(normalized_prefix, item.relative_path).as_posix()
            if normalized_prefix
            else item.relative_path
        )
        mappings.append(
            {
                "source_relative": item.relative_path,
                "target_relative": target_relative,
                "size": item.size,
            }
        )
    return mappings


def normalize_file_mappings(
    source: str | os.PathLike[str],
    mappings: Iterable[Mapping[str, Any]],
    *,
    manifest: SourcePlanManifest | None = None,
) -> list[dict[str, Any]]:
    source_manifest = manifest or build_source_plan_manifest(source)
    source_sizes = {
        item.relative_path: item.size for item in source_manifest.files
    }
    normalized: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    seen_targets: set[str] = set()

    for raw in mappings:
        source_relative = _validate_relative_mapping(
            str(raw.get("source_relative") or "")
        )
        target_relative = _validate_relative_mapping(
            str(raw.get("target_relative") or "")
        )
        if source_relative not in source_sizes:
            raise ValueError(
                f"mapped source file does not exist: {source_relative}"
            )
        if source_relative in seen_sources:
            raise ValueError(f"duplicate source mapping: {source_relative}")
        if target_relative in seen_targets:
            raise ValueError(f"duplicate target mapping: {target_relative}")

        declared_size = int(raw.get("size", source_sizes[source_relative]))
        if declared_size != source_sizes[source_relative]:
            raise ValueError(f"mapped size changed: {source_relative}")
        normalized.append(
            {
                "source_relative": source_relative,
                "target_relative": target_relative,
                "size": declared_size,
            }
        )
        seen_sources.add(source_relative)
        seen_targets.add(target_relative)

    missing = set(source_sizes) - seen_sources
    if missing:
        raise ValueError(
            f"file mappings are incomplete: {sorted(missing)[:5]}"
        )

    target_parts = {
        item["target_relative"]: PurePosixPath(item["target_relative"]).parts
        for item in normalized
    }
    target_names = set(target_parts)
    for target_relative, parts in target_parts.items():
        for index in range(1, len(parts)):
            parent = PurePosixPath(*parts[:index]).as_posix()
            if parent in target_names:
                raise ValueError(
                    "target mapping collides with a parent file: "
                    f"{parent} -> {target_relative}"
                )

    return sorted(
        normalized,
        key=lambda item: item["source_relative"].casefold(),
    )


def remap_verification_manifest(
    manifest: VerificationManifest,
    mappings: Iterable[Mapping[str, Any]],
) -> VerificationManifest:
    mapping_by_source = {
        str(item["source_relative"]): str(item["target_relative"])
        for item in mappings
    }
    remapped: list[VerifiedFile] = []
    for item in manifest.files:
        target_relative = mapping_by_source.get(item.relative_path)
        if not target_relative:
            raise ValueError(
                f"verification mapping missing: {item.relative_path}"
            )
        remapped.append(
            VerifiedFile(
                target_relative,
                item.size,
                item.digest,
                item.digest_mode,
            )
        )

    remapped.sort(key=lambda item: item.relative_path.casefold())
    records = [asdict(item) for item in remapped]
    return VerificationManifest(
        tuple(remapped),
        len(remapped),
        manifest.total_size,
        _manifest_token(records),
    )
