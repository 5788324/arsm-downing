"""Runtime path helpers for source, portable, and installed builds."""

from __future__ import annotations

import os
import sys
from pathlib import Path


INSTALL_MARKER = "arsm-installed.marker"
APP_DATA_DIRECTORY = "ARSM Suite"


def executable_dir() -> Path:
    """Return the frozen executable directory without consulting app data."""
    return Path(sys.executable).resolve().parent


def installed_data_dir() -> Path:
    """Return the per-user writable directory used by the Windows installer."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / APP_DATA_DIRECTORY


def application_dir() -> Path:
    """Return the writable application directory.

    Source runs keep the historical current-working-directory behavior. Frozen
    portable builds use the executable directory. Installer-managed builds carry
    a small marker beside the executable and keep mutable data under
    ``%LOCALAPPDATA%\\ARSM Suite`` so an in-place upgrade or uninstall never
    overwrites active downloads, settings, or the SQLite database.
    ``ARSM_APP_HOME`` is reserved for tests and isolated acceptance runs.
    """
    override = os.environ.get("ARSM_APP_HOME")
    if override:
        return Path(override).expanduser().resolve(strict=False)
    if getattr(sys, "frozen", False):
        executable_home = executable_dir()
        if (executable_home / INSTALL_MARKER).is_file():
            return installed_data_dir().resolve(strict=False)
        return executable_home
    return Path.cwd().resolve(strict=False)


def resource_dir() -> Path:
    """Return the directory containing bundled read-only resources."""
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root).resolve(strict=False)
    if getattr(sys, "frozen", False):
        return executable_dir()
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