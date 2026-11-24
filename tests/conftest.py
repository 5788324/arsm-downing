"""Shared pytest policy and fixtures.

The default gate fails closed when live application state is present in the
checkout.  This prevents an engineer from accidentally running tests against a
working directory used by an active downloader.
"""
from __future__ import annotations

import os
import signal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PROTECTED_WORKTREE_STATE = (
    REPO_ROOT / "history.db",
    REPO_ROOT / "config.json",
    REPO_ROOT / "queue.json",
)


def pytest_sessionstart(session: pytest.Session) -> None:
    if os.environ.get("ARSM_TEST_ALLOW_WORKTREE_STATE") == "1":
        return
    present = [str(path) for path in PROTECTED_WORKTREE_STATE if path.exists()]
    if present:
        pytest.exit(
            "Refusing to run the portable test gate beside live application state. "
            "Use a clean clone or a read-only database snapshot. Found: "
            + ", ".join(present),
            returncode=2,
        )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Treat unmarked tests in tests/ as portable by default."""
    for item in items:
        if not any(
            item.get_closest_marker(name)
            for name in ("portable", "manual", "windows_integration", "live_network")
        ):
            item.add_marker(pytest.mark.portable)


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "history.db"


@pytest.fixture
def temp_sandbox(tmp_path: Path) -> Path:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    return sandbox


# CI diagnostic (Linux-only): fail any single test that exceeds 60s.
# ``signal.SIGALRM`` exists only on POSIX, so this is a no-op on Windows and is
# used solely to name the test that hangs the Ubuntu CI job instead of waiting
# for the 15-minute workflow timeout.  Remove once the hang is fixed.
if hasattr(signal, "SIGALRM"):

    @pytest.fixture(autouse=True)
    def _posix_test_timeout():
        def _handler(_signum, _frame):
            raise TimeoutError("test exceeded 60s (possible hang)")

        previous = signal.signal(signal.SIGALRM, _handler)
        signal.alarm(60)
        yield
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
