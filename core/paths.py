"""Runtime path helpers for source checkouts and frozen portable builds."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def application_dir() -> Path:
    """Return the writable application directory.

    Source runs keep the historical current-working-directory behavior. Frozen
    builds use the executable directory so shortcuts do not redirect config,
    database, downloads, or logs into an arbitrary working directory.
    ``ARSM_APP_HOME`` is reserved for tests and isolated acceptance runs.
    """
    override = os.environ.get("ARSM_APP_HOME")
    if override:
        return Path(override).expanduser().resolve(strict=False)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd().resolve(strict=False)


def resource_dir() -> Path:
    """Return the directory containing bundled read-only resources."""
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root).resolve(strict=False)
    return application_dir()


def app_path(*parts: str) -> Path:
    return application_dir().joinpath(*parts)


def resource_path(*parts: str) -> Path:
    return resource_dir().joinpath(*parts)


def resolve_runtime_path(value: str | os.PathLike[str]) -> Path:
    """Resolve a configured path, anchoring relative values to app home."""
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = application_dir() / path
    return path.resolve(strict=False)
