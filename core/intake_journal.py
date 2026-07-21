"""Execution requests, durable journals and batch results for intake tasks."""
from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

JOURNAL_SCHEMA_VERSION = 1
TRANSACTION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


@dataclass(frozen=True)
class IntakeFileExecutionRequest:
    rj_id: str
    source_path: str
    target_path: str
    sandbox_root: str
    expected_preimage_token: str
    expected_source_manifest_token: str
    file_mappings: tuple[dict[str, Any], ...] = ()
    transaction_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    ensure_library_index: bool = True


@dataclass
class JournalEvent:
    state: str
    timestamp: str
    detail: str = ""


@dataclass
class IntakeExecutionJournal:
    transaction_id: str
    rj_id: str
    source_path: str
    target_path: str
    sandbox_root: str
    staging_path: str
    rollback_path: str
    expected_preimage_token: str
    expected_source_manifest_token: str
    state: str = "planned"
    success: bool = False
    stop_required: bool = False
    error_code: str = ""
    error: str = ""
    source_manifest: dict[str, Any] = field(default_factory=dict)
    verification_manifest: dict[str, Any] = field(default_factory=dict)
    database_result: dict[str, Any] = field(default_factory=dict)
    events: list[JournalEvent] = field(default_factory=list)
    schema_version: int = JOURNAL_SCHEMA_VERSION
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )
    )
    updated_at: str = ""

    def transition(self, state: str, detail: str = "") -> None:
        self.state = state
        self.updated_at = datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )
        self.events.append(JournalEvent(state, self.updated_at, detail))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any]
    ) -> "IntakeExecutionJournal":
        data = dict(payload)
        data["events"] = [
            JournalEvent(**event) for event in data.get("events", [])
        ]
        return cls(**data)


@dataclass
class IntakeBatchResult:
    journals: list[IntakeExecutionJournal] = field(default_factory=list)
    stopped: bool = False
    stop_reason: str = ""

    @property
    def completed(self) -> int:
        return sum(1 for item in self.journals if item.success)

    @property
    def failed(self) -> int:
        return sum(1 for item in self.journals if not item.success)

    def to_dict(self) -> dict[str, Any]:
        return {
            "journals": [item.to_dict() for item in self.journals],
            "stopped": self.stopped,
            "stop_reason": self.stop_reason,
            "completed": self.completed,
            "failed": self.failed,
        }


def valid_transaction_id(value: str) -> bool:
    return bool(TRANSACTION_ID_RE.fullmatch(str(value or "")))


def atomic_write_journal(
    path: str | os.PathLike[str], payload: Mapping[str, Any]
) -> None:
    journal_path = Path(path)
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = journal_path.with_suffix(journal_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    os.replace(temporary, journal_path)


def load_journal(
    path: str | os.PathLike[str],
) -> IntakeExecutionJournal:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return IntakeExecutionJournal.from_dict(payload)


def request_from_plan_action(
    action: Mapping[str, Any],
    *,
    sandbox_root: str | os.PathLike[str],
    transaction_id: str | None = None,
) -> IntakeFileExecutionRequest:
    """Build a sandbox request from a DB-annotated, unambiguous action."""
    classification = str(action.get("classification") or "")
    if classification != "needs_rename_top_level":
        raise ValueError(
            f"plan action is not sandbox-executable: {classification}"
        )
    if action.get("issues"):
        raise ValueError("plan action still requires review")

    required = {
        "rj_id": str(action.get("rj_id") or ""),
        "source_path": str(action.get("source") or ""),
        "target_path": str(action.get("target_root") or ""),
        "expected_preimage_token": str(
            action.get("db_preimage_token") or ""
        ),
        "expected_source_manifest_token": str(
            action.get("source_manifest_token") or ""
        ),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ValueError(
            f"plan action is missing required fields: {missing}"
        )

    return IntakeFileExecutionRequest(
        **required,
        sandbox_root=str(sandbox_root),
        file_mappings=tuple(
            dict(item) for item in action.get("file_mappings", [])
        ),
        transaction_id=transaction_id or uuid.uuid4().hex,
    )
