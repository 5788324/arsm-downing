from __future__ import annotations

import pytest

from core.state_policy import InvalidStateTransition, WorkStatePolicy

pytestmark = pytest.mark.portable


def test_expected_download_transitions_are_allowed() -> None:
    assert WorkStatePolicy.require("prepared", "queued").allowed
    assert WorkStatePolicy.require("queued", "downloading").allowed
    assert WorkStatePolicy.require("downloading", "paused").allowed
    assert WorkStatePolicy.require("paused", "queued").allowed
    assert WorkStatePolicy.require("downloading", "completed").allowed


def test_terminal_work_cannot_silently_return_to_queue() -> None:
    decision = WorkStatePolicy.decide("completed", "queued")
    assert decision.allowed is False
    with pytest.raises(InvalidStateTransition):
        WorkStatePolicy.require("completed", "queued")


def test_unknown_legacy_source_can_be_read_without_bulk_rewrite() -> None:
    assert WorkStatePolicy.decide("historic_custom", "paused").allowed
    assert not WorkStatePolicy.decide(
        "historic_custom", "paused", allow_legacy_source=False
    ).allowed
