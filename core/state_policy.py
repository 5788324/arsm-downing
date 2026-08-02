from __future__ import annotations

from dataclasses import dataclass


class InvalidStateTransition(ValueError):
    pass


@dataclass(frozen=True)
class StateTransitionDecision:
    current: str
    target: str
    allowed: bool
    reason: str = ""


class WorkStatePolicy:
    """Explicit transition policy for new writes without rewriting legacy rows."""

    TERMINAL = {"completed", "registered", "verified", "external", "indexed", "cancelled"}
    ALLOWED = {
        "": {"preparing", "prepared", "queued", "external", "indexed"},
        "preparing": {"prepared", "metadata_failed", "failed", "paused", "cancelled"},
        "prepared": {"queued", "metadata_failed", "paused", "failed", "cancelled"},
        "metadata_failed": {"preparing", "queued", "failed", "cancelled"},
        "queued": {"downloading", "paused", "failed", "metadata_failed", "cancelled"},
        "resuming": {"queued", "downloading", "paused", "failed", "cancelled"},
        "downloading": {"paused", "partial", "failed", "completed", "cancelled"},
        "paused": {"resuming", "queued", "failed", "cancelled"},
        "partial": {"resuming", "queued", "failed", "completed", "verified", "cancelled"},
        "failed": {"queued", "resuming", "preparing", "paused", "cancelled"},
        "cancelled": {"failed", "queued", "resuming", "preparing"},
        "completed": {"registered", "verified"},
        "registered": {"completed", "verified", "failed"},
        "verified": {"completed", "missing"},
        "external": {"verified", "partial", "missing"},
        "indexed": {"verified", "partial", "missing"},
        "missing": {"external", "indexed", "verified"},
    }

    @staticmethod
    def normalize(status: str | None) -> str:
        value = (status or "").strip().lower()
        aliases = {
            "preparing...": "preparing",
            "queued (cached)": "queued",
            "downloading": "downloading",
            "paused (partial)": "paused",
            "resuming...": "resuming",
            "no pending tracks": "no_pending",
            "partially completed": "partial",
            "canceled": "cancelled",
            "已取消": "cancelled",
        }
        if value.startswith("partially completed"):
            return "partial"
        if value.startswith("paused"):
            return "paused"
        if value.startswith("error:"):
            return "failed"
        if value.startswith("metadata failed"):
            return "metadata_failed"
        return aliases.get(value, value)

    @classmethod
    def decide(
        cls,
        current: str | None,
        target: str | None,
        *,
        allow_legacy_source: bool = True,
    ) -> StateTransitionDecision:
        source = cls.normalize(current)
        destination = cls.normalize(target)
        if source == destination:
            return StateTransitionDecision(source, destination, True, "idempotent")
        allowed_targets = cls.ALLOWED.get(source)
        if allowed_targets is None:
            return StateTransitionDecision(
                source,
                destination,
                allow_legacy_source,
                "legacy source state" if allow_legacy_source else "unknown source state",
            )
        if destination in allowed_targets:
            return StateTransitionDecision(source, destination, True)
        return StateTransitionDecision(source, destination, False, "transition not allowed")

    @classmethod
    def require(
        cls,
        current: str | None,
        target: str | None,
        *,
        allow_legacy_source: bool = True,
    ) -> StateTransitionDecision:
        decision = cls.decide(
            current,
            target,
            allow_legacy_source=allow_legacy_source,
        )
        if not decision.allowed:
            raise InvalidStateTransition(
                f"invalid work state transition: {decision.current!r} -> {decision.target!r}"
            )
        return decision
