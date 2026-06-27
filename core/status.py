"""Single source of truth for work and download states."""

from enum import Enum


class WorkStatus(Enum):
    # Active / pipeline
    PREPARING = "preparing"
    PREPARED = "prepared"
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    RESUMING = "resuming"

    # Terminal
    COMPLETED = "completed"
    REGISTERED = "registered"
    PARTIAL = "partial"

    # Error / special
    FAILED = "failed"
    METADATA_FAILED = "metadata_failed"
    NO_PENDING = "no_pending"
    STALE = "stale"
    IGNORED = "ignored"

    # Library-only
    DUPLICATE = "duplicate"
    EXTERNAL = "external"
    VERIFIED = "verified"
    MISSING = "missing"
    INDEXED = "indexed"

    # Internal transient, never persisted
    ALREADY_QUEUED = "already_queued"
    ALREADY_RUNNING = "already_running"

    @property
    def is_active(self) -> bool:
        return self in (
            WorkStatus.PREPARING,
            WorkStatus.PREPARED,
            WorkStatus.QUEUED,
            WorkStatus.DOWNLOADING,
            WorkStatus.RESUMING,
        )

    @property
    def is_pausable(self) -> bool:
        return self in (
            WorkStatus.QUEUED,
            WorkStatus.DOWNLOADING,
            WorkStatus.PREPARED,
        )

    @property
    def is_resumable(self) -> bool:
        return self in (WorkStatus.QUEUED, WorkStatus.PAUSED)

    @property
    def is_terminal(self) -> bool:
        return self in (
            WorkStatus.COMPLETED,
            WorkStatus.REGISTERED,
            WorkStatus.VERIFIED,
            WorkStatus.EXTERNAL,
            WorkStatus.INDEXED,
            WorkStatus.STALE,
            WorkStatus.IGNORED,
        )

    @property
    def needs_metadata_retry(self) -> bool:
        return self in (WorkStatus.METADATA_FAILED, WorkStatus.NO_PENDING)

    @property
    def ui_label(self) -> str:
        labels = {
            WorkStatus.PREPARING: "???...",
            WorkStatus.PREPARED: "???",
            WorkStatus.QUEUED: "???",
            WorkStatus.DOWNLOADING: "???",
            WorkStatus.PAUSED: "???",
            WorkStatus.RESUMING: "???...",
            WorkStatus.COMPLETED: "???",
            WorkStatus.REGISTERED: "???",
            WorkStatus.PARTIAL: "????",
            WorkStatus.FAILED: "????",
            WorkStatus.METADATA_FAILED: "?????",
            WorkStatus.NO_PENDING: "??????",
            WorkStatus.STALE: "????",
            WorkStatus.IGNORED: "???",
            WorkStatus.DUPLICATE: "??",
            WorkStatus.EXTERNAL: "????",
            WorkStatus.VERIFIED: "???",
            WorkStatus.MISSING: "????",
            WorkStatus.INDEXED: "???",
        }
        return labels.get(self, self.value)

    @staticmethod
    def normalize(status: str) -> "WorkStatus":
        s = (status or "").strip()
        if not s:
            return WorkStatus.QUEUED

        s_lower = s.lower()

        if any(k in s_lower for k in (
            "metadata_failed",
            "metadata failed",
            "metadata proxy failed",
        )) or s in ("???????", "?????", "???????"):
            return WorkStatus.METADATA_FAILED

        if any(k in s_lower for k in ("no pending", "no_pending", "no pending tracks")) or s == "????":
            return WorkStatus.NO_PENDING

        if s in ("stale", "????"):
            return WorkStatus.STALE
        if s in ("ignored", "???"):
            return WorkStatus.IGNORED

        if "??" in s or "duplicate" in s_lower:
            return WorkStatus.DUPLICATE

        if s.startswith("Failed") or s.startswith("Error") or s in ("failed", "????"):
            return WorkStatus.FAILED

        if s in ("???", "Completed", "completed", "registered"):
            return WorkStatus.COMPLETED

        if "Partially completed" in s or "????" in s or s == "partial":
            return WorkStatus.PARTIAL

        if s in ("???", "Paused", "Paused (partial)", "paused"):
            return WorkStatus.PAUSED

        if s in ("Preparing", "???..."):
            return WorkStatus.PREPARING
        if s in ("Prepared", "Prepared (cached)", "???"):
            return WorkStatus.PREPARED
        if s in ("Queued", "Queued (cached)", "???", "?????"):
            return WorkStatus.QUEUED
        if s in ("Downloading", "???"):
            return WorkStatus.DOWNLOADING
        if s in ("Resuming...", "???..."):
            return WorkStatus.RESUMING
        if s in ("external", "????"):
            return WorkStatus.EXTERNAL
        if s in ("verified", "???"):
            return WorkStatus.VERIFIED
        if s in ("missing", "????"):
            return WorkStatus.MISSING
        if s in ("indexed", "???"):
            return WorkStatus.INDEXED
        if s == "already_queued":
            return WorkStatus.QUEUED
        if s == "already_running":
            return WorkStatus.DOWNLOADING

        return WorkStatus.QUEUED
