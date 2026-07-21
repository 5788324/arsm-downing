from __future__ import annotations

import importlib

import pytest

pytestmark = pytest.mark.portable


@pytest.mark.parametrize(
    "module_name",
    [
        "core.audio",
        "core.paths",
        "core.version",
        "core.config",
        "core.database",
        "core.database_snapshot",
        "core.intake_db",
        "core.intake_fs",
        "core.intake_journal",
        "core.intake_manifest",
        "core.migration",
        "core.network",
        "core.orchestrator",
        "tools.external_intake",
        "ui.app",
        "ui.views.download_view",
        "ui.views.library_view",
        "ui.views.settings_view",
        "ui.views.tools_view",
    ],
)
def test_module_imports(module_name: str) -> None:
    importlib.import_module(module_name)


def test_flet_legacy_api_surface_is_available() -> None:
    import flet as ft

    assert hasattr(ft, "icons")
    assert hasattr(ft, "colors")
