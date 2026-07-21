"""Filesystem manifests used by the safe migration engine.

The manifest is intentionally independent from SQLite.  It gives migration a
stable, auditable description of a directory tree and rejects links or partial
files before any copy/delete operation begins.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

PART_SUFFIX = ".part"
FULL_HASH_LIMIT = 8 * 1024 * 1024
SAMPLE_BYTES = 1024 * 1024
CRITICAL_EXTENSIONS = {
    ".json", ".txt", ".lrc", ".cue", ".jpg", ".jpeg", ".png", ".webp",
}


class MigrationManifestError(RuntimeError):
    """Raised when a source tree cannot be safely represented."""


@dataclass(frozen=True)
class MigrationManifestEntry:
    relative_path: str
    size: int
    mtime_ns: int
    digest: str
    digest_mode: str


@dataclass(frozen=True)
class MigrationManifest:
    root: str
    entries: tuple[MigrationManifestEntry, ...]
    total_bytes: int
    token: str

    @property
    def file_count(self) -> int:
        return len(self.entries)

    def to_dict(self) -> dict:
        return {
            "root": self.root,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "token": self.token,
            "entries": [asdict(entry) for entry in self.entries],
        }

    def file_mappings(self, target_root: str | Path) -> dict[str, str]:
        target = Path(target_root)
        source = Path(self.root)
        return {
            str(source / Path(entry.relative_path)): str(target / Path(entry.relative_path))
            for entry in self.entries
        }


def _sha256_full(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_sample(path: Path, size: int) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        digest.update(handle.read(SAMPLE_BYTES))
        if size > SAMPLE_BYTES:
            handle.seek(max(0, size - SAMPLE_BYTES))
            digest.update(handle.read(SAMPLE_BYTES))
    digest.update(str(size).encode("ascii"))
    return digest.hexdigest()


def _digest_for(path: Path, size: int) -> tuple[str, str]:
    if size <= FULL_HASH_LIMIT or path.suffix.casefold() in CRITICAL_EXTENSIONS:
        return _sha256_full(path), "sha256"
    return _sha256_sample(path, size), "sha256_sample"


def _stable_token(entries: Iterable[MigrationManifestEntry]) -> str:
    payload = [asdict(entry) for entry in entries]
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_migration_manifest(root: str | Path) -> MigrationManifest:
    original_root = Path(root).expanduser()
    if original_root.is_symlink():
        raise MigrationManifestError(f"source root is a symlink: {original_root}")
    root_path = original_root.resolve(strict=True)
    if not root_path.is_dir():
        raise MigrationManifestError(f"source is not a directory: {root_path}")

    entries: list[MigrationManifestEntry] = []
    try:
        for current, dir_names, file_names in os.walk(root_path, followlinks=False):
            current_path = Path(current)
            for name in list(dir_names):
                directory = current_path / name
                if directory.is_symlink():
                    raise MigrationManifestError(
                        f"symlink directory is not allowed: {directory}"
                    )
            for name in file_names:
                file_path = current_path / name
                if file_path.is_symlink():
                    raise MigrationManifestError(
                        f"symlink file is not allowed: {file_path}"
                    )
                if name.casefold().endswith(PART_SUFFIX):
                    raise MigrationManifestError(
                        f"partial download is not migratable: {file_path}"
                    )
                stat = file_path.stat()
                relative = file_path.relative_to(root_path).as_posix()
                digest, digest_mode = _digest_for(file_path, stat.st_size)
                entries.append(
                    MigrationManifestEntry(
                        relative_path=relative,
                        size=stat.st_size,
                        mtime_ns=stat.st_mtime_ns,
                        digest=digest,
                        digest_mode=digest_mode,
                    )
                )
    except OSError as exc:
        raise MigrationManifestError(str(exc)) from exc

    entries.sort(key=lambda item: item.relative_path.casefold())
    if not entries:
        raise MigrationManifestError(f"source contains no files: {root_path}")
    frozen = tuple(entries)
    return MigrationManifest(
        root=str(root_path),
        entries=frozen,
        total_bytes=sum(entry.size for entry in frozen),
        token=_stable_token(frozen),
    )


def compare_manifest_to_tree(
    manifest: MigrationManifest,
    candidate_root: str | Path,
    *,
    require_mtime: bool = False,
) -> tuple[bool, list[str]]:
    candidate = Path(candidate_root).expanduser().resolve(strict=False)
    issues: list[str] = []
    if not candidate.is_dir():
        return False, [f"directory_missing:{candidate}"]

    expected = {entry.relative_path: entry for entry in manifest.entries}
    actual_paths: set[str] = set()
    try:
        for current, dir_names, file_names in os.walk(candidate, followlinks=False):
            current_path = Path(current)
            for name in list(dir_names):
                directory = current_path / name
                if directory.is_symlink():
                    issues.append(f"symlink_directory:{directory}")
            for name in file_names:
                file_path = current_path / name
                relative = file_path.relative_to(candidate).as_posix()
                actual_paths.add(relative)
                if file_path.is_symlink():
                    issues.append(f"symlink_file:{relative}")
                    continue
                entry = expected.get(relative)
                if entry is None:
                    issues.append(f"unexpected_file:{relative}")
                    continue
                stat = file_path.stat()
                if stat.st_size != entry.size:
                    issues.append(
                        f"size_mismatch:{relative}:{entry.size}:{stat.st_size}"
                    )
                    continue
                if require_mtime and stat.st_mtime_ns != entry.mtime_ns:
                    issues.append(f"mtime_mismatch:{relative}")
                digest = (
                    _sha256_full(file_path)
                    if entry.digest_mode == "sha256"
                    else _sha256_sample(file_path, stat.st_size)
                )
                if digest != entry.digest:
                    issues.append(f"hash_mismatch:{relative}")
    except OSError as exc:
        issues.append(f"filesystem_error:{exc}")

    missing = sorted(set(expected) - actual_paths)
    issues.extend(f"missing_file:{path}" for path in missing)
    return not issues, issues


def contains_recursive_part_file(root: str | Path) -> bool:
    try:
        for current, _, file_names in os.walk(root, followlinks=False):
            if any(name.casefold().endswith(PART_SUFFIX) for name in file_names):
                return True
    except OSError:
        return True
    return False
