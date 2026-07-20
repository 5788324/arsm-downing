from pathlib import Path
from types import SimpleNamespace

import ui.views.library_view as library_module
from ui.views.library_view import LibraryView, open_folder


class FakeDb:
    def __init__(self):
        self.page_calls = []

    def get_library_page(self, **kwargs):
        self.page_calls.append(kwargs)
        return {
            "items": [],
            "total": 0,
            "works_count": 3,
            "summary": {
                "total_works": 2,
                "total_files": 9,
                "total_size": 1000,
                "with_warnings": 1,
            },
        }

    def get_library_diagnostic_rows(self):
        return {
            "works": [],
            "library_items": [],
            "works_count": 3,
            "summary": {"total_works": 2, "total_files": 9, "total_size": 1000, "with_warnings": 1},
        }


class FakeController:
    def __init__(self, tmp_path: Path):
        self.db = FakeDb()
        self.config = SimpleNamespace(
            output_dir=tmp_path / "Downloads",
            library_paths=[str(tmp_path / "Library")],
        )
        self.snacks = []

    def run_blocking(self, function, on_success, **_kwargs):
        on_success(function())

    def show_snack(self, message):
        self.snacks.append(message)


def test_library_search_is_forwarded_to_database(tmp_path: Path) -> None:
    controller = FakeController(tmp_path)
    view = LibraryView(controller)
    view.search_input.value = "RJ00000042"
    view.on_search()
    assert controller.db.page_calls[-1]["search"] == "RJ00000042"
    assert "搜索“RJ00000042”" in view.page_info.value


def test_library_summary_is_dynamic(tmp_path: Path) -> None:
    view = LibraryView(FakeController(tmp_path))
    view.load_library()
    assert "下载器记录 3" in view.summary_bar.value
    assert "已索引 2" in view.summary_bar.value
    assert "磁盘扫描" not in view.summary_bar.value


def test_search_change_does_not_reload_for_each_nonempty_keystroke(tmp_path: Path) -> None:
    controller = FakeController(tmp_path)
    view = LibraryView(controller)
    initial = len(controller.db.page_calls)
    view.search_input.value = "R"
    view._on_search_change()
    assert len(controller.db.page_calls) == initial
    view.search_input.value = ""
    view._on_search_change()
    assert len(controller.db.page_calls) == initial + 1


def test_open_folder_reports_missing_path(tmp_path: Path) -> None:
    ok, message = open_folder(tmp_path / "missing")
    assert not ok
    assert "目录不存在" in message


def test_open_folder_uses_platform_command(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "folder"
    target.mkdir()
    calls = []
    monkeypatch.setattr(library_module.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        library_module.subprocess,
        "run",
        lambda args, check: calls.append((args, check)),
    )
    ok, _message = open_folder(target)
    assert ok
    assert calls == [(["xdg-open", str(target)], True)]


def test_library_vault_page_search_and_cover_join(tmp_path: Path) -> None:
    from core.database import LibraryVault
    import json
    from datetime import datetime

    db_path = tmp_path / "history.db"
    with LibraryVault(db_path) as vault:
        vault.execute_write(
            "INSERT INTO works (rj_id, title, local_path, status) VALUES (?, ?, ?, ?)",
            ("RJ00000042", "Needle", str(tmp_path / "Needle"), "completed"),
        )
        vault.execute_write(
            """INSERT INTO library_items
               (rj_id, folder_path, folder_name, total_files, total_size,
                audio_count, has_audio, has_cover, warnings_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("RJ00000042", str(tmp_path / "Needle"), "Needle Folder", 3, 1234, 2, 1, 0, "[]"),
        )
        vault.execute_write(
            """INSERT INTO metadata_cache
               (rj_id, title, circle, cover_url, metadata_json, tracks_json,
                fetched_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("RJ00000042", "Needle", "Circle", "https://example.invalid/cover.jpg",
             json.dumps({}), json.dumps([]), datetime.now(), datetime.now()),
        )
        result = vault.get_library_page(search="Needle", offset=0, limit=20)

    assert result["total"] == 1
    assert result["works_count"] == 1
    assert result["items"][0]["rj_id"] == "RJ00000042"
    assert result["items"][0]["metadata_cover_url"] == "https://example.invalid/cover.jpg"
