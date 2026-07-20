"""Sandboxed external-intake filesystem transactions and recovery journals."""
from __future__ import annotations

import os
import shutil
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Protocol

from core.intake_journal import (
    IntakeBatchResult,
    IntakeExecutionJournal,
    IntakeFileExecutionRequest,
    atomic_write_journal,
    load_journal,
    request_from_plan_action,
    valid_transaction_id,
)
from core.intake_manifest import (
    build_identity_file_mappings,
    build_source_plan_manifest,
    build_verification_manifest,
    compare_verification_manifests,
    iter_regular_files,
    normalize_file_mappings,
    remap_verification_manifest,
)

class VaultLike(Protocol):
    def update_external_intake_paths(
        self,
        rj_id: str,
        source_path: str,
        target_path: str,
        *,
        expected_preimage_token: str = "",
        ensure_library_index: bool = True,
        file_path_mappings: dict[str, str] | None = None,
    ) -> dict[str, Any]: ...


class SimulatedProcessInterruption(BaseException):
    """Test-only crash signal that intentionally bypasses normal rollback."""


FaultInjector = Callable[[str, IntakeExecutionJournal], None]


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _is_within(parent: Path, child: Path) -> bool:
    try:
        _resolved(child).relative_to(_resolved(parent))
        return True
    except (ValueError, OSError, RuntimeError):
        return False


def _copy_mapped_files(
    source: Path,
    staging: Path,
    mappings: Iterable[Mapping[str, Any]],
) -> None:
    staging.mkdir(parents=True, exist_ok=False)
    for item in mappings:
        source_file = source.joinpath(
            *PurePosixPath(item["source_relative"]).parts
        )
        target_file = staging.joinpath(
            *PurePosixPath(item["target_relative"]).parts
        )
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target_file)


class ExternalIntakeSandboxExecutor:
    """Execute copied-library actions inside an explicit sandbox root only."""

    def __init__(
        self,
        vault: VaultLike,
        journal_dir: str | os.PathLike[str],
        *,
        fault_injector: FaultInjector | None = None,
    ) -> None:
        self.vault = vault
        self.journal_dir = Path(journal_dir)
        self.fault_injector = fault_injector

    def _journal_path(self, transaction_id: str) -> Path:
        if not valid_transaction_id(transaction_id):
            raise ValueError("invalid transaction id")
        return self.journal_dir / f"{transaction_id}.json"

    def _persist(self, journal: IntakeExecutionJournal) -> None:
        atomic_write_journal(
            self._journal_path(journal.transaction_id),
            journal.to_dict(),
        )

    def _transition(
        self,
        journal: IntakeExecutionJournal,
        state: str,
        detail: str = "",
    ) -> None:
        journal.transition(state, detail)
        self._persist(journal)

    def _inject(
        self, stage: str, journal: IntakeExecutionJournal
    ) -> None:
        if self.fault_injector is not None:
            self.fault_injector(stage, journal)

    def _paths_for_request(
        self, request: IntakeFileExecutionRequest
    ) -> tuple[Path, Path, Path, Path, Path]:
        sandbox = _resolved(Path(request.sandbox_root))
        source = _resolved(Path(request.source_path))
        target = _resolved(Path(request.target_path))
        staging = (
            target.parent
            / ".arsm-intake-staging"
            / request.transaction_id
        )
        rollback = (
            source.parent
            / f".{source.name}.arsm-rollback-{request.transaction_id}"
        )
        return sandbox, source, target, staging, rollback

    def _new_journal(
        self, request: IntakeFileExecutionRequest
    ) -> IntakeExecutionJournal:
        sandbox, source, target, staging, rollback = (
            self._paths_for_request(request)
        )
        journal = IntakeExecutionJournal(
            transaction_id=request.transaction_id,
            rj_id=request.rj_id,
            source_path=str(source),
            target_path=str(target),
            sandbox_root=str(sandbox),
            staging_path=str(staging),
            rollback_path=str(rollback),
            expected_preimage_token=request.expected_preimage_token,
            expected_source_manifest_token=(
                request.expected_source_manifest_token
            ),
        )
        journal.transition("planned", "sandbox execution request created")
        self._persist(journal)
        return journal

    def _validate_request(
        self,
        request: IntakeFileExecutionRequest,
        sandbox: Path,
        source: Path,
        target: Path,
        staging: Path,
        rollback: Path,
    ) -> tuple[bool, str, str]:
        if not request.rj_id.strip():
            return False, "invalid_rj_id", "rj_id is required"
        if not request.expected_preimage_token:
            return (
                False,
                "missing_preimage_token",
                "database preimage token is required",
            )
        if not request.expected_source_manifest_token:
            return (
                False,
                "missing_manifest_token",
                "source manifest token is required",
            )
        if (
            not sandbox.exists()
            or not sandbox.is_dir()
            or sandbox.is_symlink()
        ):
            return (
                False,
                "invalid_sandbox",
                "sandbox root must be an existing real directory",
            )

        guarded_paths = (
            ("source", source),
            ("target", target),
            ("staging", staging),
            ("rollback", rollback),
        )
        for label, path in guarded_paths:
            if not _is_within(sandbox, path):
                return (
                    False,
                    "outside_sandbox",
                    f"{label} path is outside sandbox root",
                )

        if source == target:
            return (
                False,
                "same_path",
                "source and target resolve to the same path",
            )
        if _is_within(source, target) or _is_within(target, source):
            return (
                False,
                "nested_paths",
                "source and target may not contain one another",
            )
        if (
            not source.exists()
            or not source.is_dir()
            or source.is_symlink()
        ):
            return (
                False,
                "invalid_source",
                "source must be an existing real directory",
            )

        try:
            source_files = iter_regular_files(source)
        except (OSError, ValueError) as exc:
            return False, "unsafe_source_tree", str(exc)
        if not source_files:
            return False, "empty_source", "source contains no regular files"
        if target.exists():
            return False, "target_exists", "target path already exists"
        if staging.exists() or rollback.exists():
            return (
                False,
                "transaction_path_exists",
                "staging or rollback path already exists",
            )
        if any(
            path.name.casefold().endswith(".part")
            for path in source_files
        ):
            return (
                False,
                "part_files_present",
                "source contains .part files",
            )
        return True, "", ""

    def execute(
        self, request: IntakeFileExecutionRequest
    ) -> IntakeExecutionJournal:
        if not valid_transaction_id(request.transaction_id):
            raise ValueError("invalid transaction id")
        sandbox_root = _resolved(Path(request.sandbox_root))
        journal_dir = _resolved(self.journal_dir)
        if (
            not sandbox_root.exists()
            or not sandbox_root.is_dir()
            or sandbox_root.is_symlink()
            or not _is_within(sandbox_root, journal_dir)
            or (self.journal_dir.exists() and self.journal_dir.is_symlink())
        ):
            raise ValueError("journal directory must be a real path inside sandbox")
        journal = self._new_journal(request)
        sandbox, source, target, staging, rollback = (
            self._paths_for_request(request)
        )
        valid, code, message = self._validate_request(
            request,
            sandbox,
            source,
            target,
            staging,
            rollback,
        )
        if not valid:
            journal.error_code = code
            journal.error = message
            self._transition(journal, "failed", message)
            return journal

        try:
            source_plan = build_source_plan_manifest(source)
            journal.source_manifest = source_plan.to_dict()
            if (
                source_plan.token
                != request.expected_source_manifest_token
            ):
                journal.error_code = "source_plan_changed"
                journal.error = (
                    "source tree changed after the plan was created"
                )
                self._transition(journal, "failed", journal.error)
                return journal

            source_verification = build_verification_manifest(source)
            requested_mappings = request.file_mappings or tuple(
                build_identity_file_mappings(source, manifest=source_plan)
            )
            normalized_mappings = normalize_file_mappings(
                source,
                requested_mappings,
                manifest=source_plan,
            )
            target_verification = remap_verification_manifest(
                source_verification,
                normalized_mappings,
            )
            journal.verification_manifest = target_verification.to_dict()
            self._transition(
                journal,
                "started",
                "source manifest and file mappings revalidated",
            )
            self._inject("before_stage_copy", journal)

            staging.parent.mkdir(parents=True, exist_ok=True)
            _copy_mapped_files(source, staging, normalized_mappings)
            staged_manifest = build_verification_manifest(staging)
            matches, reason = compare_verification_manifests(
                target_verification,
                staged_manifest,
            )
            if not matches:
                raise RuntimeError(
                    f"staging verification failed: {reason}"
                )
            self._transition(journal, "staged", "staging copy verified")
            self._inject("after_stage_copy", journal)

            rollback.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, rollback)
            self._transition(
                journal,
                "source_parked",
                "source renamed to rollback path",
            )
            self._inject("after_source_parked", journal)

            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, target)
            self._transition(
                journal,
                "target_committed",
                "verified staging promoted to target",
            )
            self._inject("after_target_commit", journal)

            target_manifest = build_verification_manifest(target)
            matches, reason = compare_verification_manifests(
                target_verification,
                target_manifest,
            )
            if not matches:
                raise RuntimeError(
                    f"target verification failed: {reason}"
                )
            self._transition(
                journal,
                "verified",
                "target tree verified before database update",
            )
            self._inject("before_db_update", journal)

            database_file_mappings = {
                str(
                    source.joinpath(
                        *PurePosixPath(item["source_relative"]).parts
                    )
                ): str(
                    target.joinpath(
                        *PurePosixPath(item["target_relative"]).parts
                    )
                )
                for item in normalized_mappings
            }
            db_result = self.vault.update_external_intake_paths(
                request.rj_id,
                str(source),
                str(target),
                expected_preimage_token=(
                    request.expected_preimage_token
                ),
                ensure_library_index=request.ensure_library_index,
                file_path_mappings=database_file_mappings,
            )
            journal.database_result = dict(db_result)
            if not db_result.get("success"):
                journal.error_code = str(
                    db_result.get("error_code")
                    or "database_update_failed"
                )
                journal.error = str(
                    db_result.get("error")
                    or "database path update failed"
                )
                raise RuntimeError(journal.error)
            self._transition(
                journal,
                "db_updated",
                "database paths updated",
            )
            self._inject("after_db_update", journal)

            try:
                shutil.rmtree(rollback)
            except OSError as exc:
                journal.error_code = "rollback_cleanup_failed"
                journal.error = str(exc)
                journal.stop_required = True
                self._transition(
                    journal,
                    "cleanup_pending",
                    "database and target are committed, but rollback copy "
                    "could not be removed",
                )
                return journal

            journal.success = True
            self._transition(
                journal,
                "completed",
                "source backup removed; transaction complete",
            )
            return journal
        except SimulatedProcessInterruption:
            raise
        except Exception as exc:
            if not journal.error:
                journal.error = str(exc)
            if not journal.error_code:
                journal.error_code = "filesystem_transaction_failed"
            if journal.state == "db_updated":
                journal.stop_required = True
                self._transition(
                    journal,
                    "cleanup_pending",
                    "post-commit error; target and rollback copy preserved",
                )
                return journal

            recovered, recovery_error = self._rollback_filesystem(journal)
            if recovered:
                self._transition(journal, "rolled_back", journal.error)
            else:
                journal.stop_required = True
                if recovery_error:
                    journal.error = (
                        f"{journal.error}; rollback failed: "
                        f"{recovery_error}"
                    )
                self._transition(
                    journal,
                    "stop_required",
                    journal.error,
                )
            return journal

    def _rollback_filesystem(
        self, journal: IntakeExecutionJournal
    ) -> tuple[bool, str]:
        source = Path(journal.source_path)
        target = Path(journal.target_path)
        staging = Path(journal.staging_path)
        rollback = Path(journal.rollback_path)
        errors: list[str] = []

        try:
            if target.exists():
                if target.is_symlink() or not target.is_dir():
                    raise OSError(
                        f"unsafe target during rollback: {target}"
                    )
                shutil.rmtree(target)
        except OSError as exc:
            errors.append(str(exc))

        try:
            if rollback.exists():
                if source.exists():
                    raise OSError(
                        f"source already exists during rollback: {source}"
                    )
                os.replace(rollback, source)
        except OSError as exc:
            errors.append(str(exc))

        try:
            if staging.exists():
                if staging.is_symlink() or not staging.is_dir():
                    raise OSError(
                        f"unsafe staging during rollback: {staging}"
                    )
                shutil.rmtree(staging)
        except OSError as exc:
            errors.append(str(exc))

        return not errors, "; ".join(errors)

    def _journal_is_safe(
        self,
        journal_path: Path,
        journal: IntakeExecutionJournal,
    ) -> tuple[bool, str]:
        if not _is_within(self.journal_dir, journal_path):
            return (
                False,
                "journal file is outside the configured journal directory",
            )
        if not valid_transaction_id(journal.transaction_id):
            return False, "journal transaction id is invalid"
        if journal_path.stem != journal.transaction_id:
            return False, "journal filename does not match transaction id"

        sandbox = _resolved(Path(journal.sandbox_root))
        if (
            not sandbox.exists()
            or not sandbox.is_dir()
            or sandbox.is_symlink()
        ):
            return False, "journal sandbox is unavailable or unsafe"

        guarded_paths = (
            ("source", journal.source_path),
            ("target", journal.target_path),
            ("staging", journal.staging_path),
            ("rollback", journal.rollback_path),
        )
        for label, raw_path in guarded_paths:
            if not _is_within(sandbox, Path(raw_path)):
                return (
                    False,
                    f"journal {label} path is outside sandbox",
                )
        return True, ""

    def recover(
        self, journal_path: str | os.PathLike[str]
    ) -> IntakeExecutionJournal:
        """Recover a transaction interrupted before or after DB commit."""
        path = _resolved(Path(journal_path))
        journal = load_journal(path)
        safe, safety_error = self._journal_is_safe(path, journal)
        if not safe:
            journal.stop_required = True
            journal.error_code = "unsafe_journal"
            journal.error = safety_error
            journal.transition("stop_required", safety_error)
            return journal

        source = Path(journal.source_path)
        target = Path(journal.target_path)
        rollback = Path(journal.rollback_path)

        if journal.state in {"completed", "rolled_back"}:
            return journal

        if journal.state in {"db_updated", "cleanup_pending"}:
            if (
                not target.exists()
                or not target.is_dir()
                or target.is_symlink()
            ):
                journal.stop_required = True
                journal.error_code = "committed_target_missing"
                journal.error = (
                    "database was updated but committed target is unavailable"
                )
                self._transition(
                    journal,
                    "stop_required",
                    journal.error,
                )
                return journal

            if rollback.exists():
                try:
                    shutil.rmtree(rollback)
                except OSError as exc:
                    journal.stop_required = True
                    journal.error_code = "rollback_cleanup_failed"
                    journal.error = str(exc)
                    self._transition(
                        journal,
                        "cleanup_pending",
                        journal.error,
                    )
                    return journal

            journal.success = True
            self._transition(
                journal,
                "completed",
                "interrupted committed transaction finalized",
            )
            return journal

        recovered, error = self._rollback_filesystem(journal)
        if recovered and source.exists() and not target.exists():
            journal.success = False
            journal.error_code = "interrupted_transaction_recovered"
            journal.error = (
                "interrupted transaction restored to original source"
            )
            self._transition(
                journal,
                "rolled_back",
                journal.error,
            )
        else:
            journal.stop_required = True
            journal.error_code = "automatic_recovery_failed"
            journal.error = (
                error
                or "filesystem recovery did not restore the expected state"
            )
            self._transition(
                journal,
                "stop_required",
                journal.error,
            )
        return journal

    def execute_batch(
        self,
        requests: Iterable[IntakeFileExecutionRequest],
        *,
        stop_on_failure: bool = True,
    ) -> IntakeBatchResult:
        result = IntakeBatchResult()
        for request in requests:
            journal = self.execute(request)
            result.journals.append(journal)
            if not journal.success and stop_on_failure:
                result.stopped = True
                result.stop_reason = (
                    journal.error_code
                    or journal.error
                    or "item_failed"
                )
                break
            if journal.stop_required:
                result.stopped = True
                result.stop_reason = (
                    journal.error_code or "stop_required"
                )
                break
        return result
