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
        "core.services.download_service",
        "core.metadata_scheduler",
        "core.state_policy",
        "core.read_models",
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


def test_achievement_page_is_removed() -> None:
    from pathlib import Path

    app_source = Path("ui/app.py").read_text(encoding="utf-8")
    assert "统计与成就" not in app_source
    assert "destinations.pop(2)" in app_source
